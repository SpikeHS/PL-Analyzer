"""Multi-material raw peak selection and tabular result presentation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QAbstractTableModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.configuration import MaterialDatabase, MaterialRecord
from core.models import MaterialSearchWindow, PeakTableRecord
from ui.qt_compat import normalize_check_state


@dataclass(slots=True)
class MaterialWindowState:
    """Editable UI state for one material database entry."""

    material: MaterialRecord
    selected: bool
    min_nm: float | None
    max_nm: float | None


class MaterialWindowModel(QAbstractTableModel):
    """Checkable material rows with independently editable wavelength windows."""

    invalid_window_selected = Signal(str)
    settings_changed = Signal()
    _HEADERS = (
        QT_TRANSLATE_NOOP("MaterialWindowModel", "Material"),
        QT_TRANSLATE_NOOP("MaterialWindowModel", "Min (nm)"),
        QT_TRANSLATE_NOOP("MaterialWindowModel", "Max (nm)"),
    )

    def __init__(self, database: MaterialDatabase, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._states = [
            MaterialWindowState(
                material=material,
                selected=material.default_selected,
                min_nm=(
                    material.default_peak_window_nm[0]
                    if material.default_peak_window_nm is not None
                    else None
                ),
                max_nm=(
                    material.default_peak_window_nm[1]
                    if material.default_peak_window_nm is not None
                    else None
                ),
            )
            for material in database.materials
        ]

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._states)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self._HEADERS)
        ):
            return self.tr(self._HEADERS[section])
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._states):
            return None
        state = self._states[index.row()]
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return state.material.display_name
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if state.selected else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.ToolTipRole:
                return (
                    self.tr(state.material.notes)
                    if state.material.notes
                    else self.tr("Material search window")
                )
        elif index.column() in {1, 2}:
            value = state.min_nm if index.column() == 1 else state.max_nm
            if role == Qt.ItemDataRole.DisplayRole:
                return "" if value is None else f"{value:.3f}"
            if role == Qt.ItemDataRole.EditRole:
                return value
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        else:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:  # noqa: N802
        if not index.isValid() or not 0 <= index.row() < len(self._states):
            return False
        state = self._states[index.row()]
        if index.column() == 0 and role == Qt.ItemDataRole.CheckStateRole:
            check_state = normalize_check_state(value)
            if check_state is None:
                return False
            selected = check_state == Qt.CheckState.Checked
            if selected and not _valid_window(state.min_nm, state.max_nm):
                self.invalid_window_selected.emit(state.material.display_name)
                return False
            state.selected = selected
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            self.settings_changed.emit()
            return True
        if index.column() in {1, 2} and role == Qt.ItemDataRole.EditRole:
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                return False
            if not 0 < numeric_value <= 100000:
                return False
            proposed_minimum = numeric_value if index.column() == 1 else state.min_nm
            proposed_maximum = numeric_value if index.column() == 2 else state.max_nm
            if (
                proposed_minimum is not None
                and proposed_maximum is not None
                and proposed_minimum >= proposed_maximum
            ):
                return False
            state.min_nm = proposed_minimum
            state.max_nm = proposed_maximum
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole])
            self.settings_changed.emit()
            return True
        return False

    def selected_windows(self) -> tuple[MaterialSearchWindow, ...]:
        """Return every checked, valid material window."""

        windows: list[MaterialSearchWindow] = []
        for state in self._states:
            if not state.selected or not _valid_window(state.min_nm, state.max_nm):
                continue
            assert state.min_nm is not None
            assert state.max_nm is not None
            windows.append(
                MaterialSearchWindow(
                    material_id=state.material.material_id,
                    material_name=state.material.display_name,
                    min_nm=state.min_nm,
                    max_nm=state.max_nm,
                )
            )
        return tuple(windows)

    def set_all_with_windows(self, selected: bool) -> None:
        """Select or clear every row that has a valid window."""

        if not self._states:
            return
        for state in self._states:
            state.selected = selected and _valid_window(state.min_nm, state.max_nm)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._states) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole],
        )
        self.settings_changed.emit()

    def snapshot(self) -> tuple[dict[str, object], ...]:
        """Return JSON-ready operator edits for project persistence."""

        return tuple(
            {
                "material_id": state.material.material_id,
                "display_name": state.material.display_name,
                "selected": state.selected,
                "min_nm": state.min_nm,
                "max_nm": state.max_nm,
            }
            for state in self._states
        )

    def restore(self, snapshots: Sequence[Mapping[str, object]]) -> None:
        """Restore matching rows while retaining newly added database materials."""

        by_id = {str(item.get("material_id")): item for item in snapshots}
        for state in self._states:
            item = by_id.get(state.material.material_id)
            if item is None:
                continue
            minimum = item.get("min_nm")
            maximum = item.get("max_nm")
            state.min_nm = float(minimum) if minimum is not None else None
            state.max_nm = float(maximum) if maximum is not None else None
            state.selected = bool(item.get("selected")) and _valid_window(
                state.min_nm,
                state.max_nm,
            )
        if self._states:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._states) - 1, 2),
            )


class PeakTableModel(QAbstractTableModel):
    """Checkable, sortable table model for material-labelled raw peaks.

    Column 0 is the operator's keep/ignore decision for each detected peak.
    Unchecked rows stay readable but no longer reach the plot markers, the
    clipboard copy, or any results export. Every other column sorts by its
    numeric or text value, never by the rendered string.
    """

    inclusion_changed = Signal(str, float, bool)
    _HEADERS = (
        QT_TRANSLATE_NOOP("PeakTableModel", "Include"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Sample"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Material"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Peak"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Position\n(nm)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Height\n(a.u.)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "FWHM\n(nm)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Prominence\n(a.u.)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Quality"),
    )
    # Clipboard layout: no header row, three columns only — sample, peak
    # position with its unit, peak height.
    _NUMERIC_COLUMNS = (4, 5, 6, 7)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: tuple[PeakTableRecord, ...] = ()
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    @property
    def records(self) -> tuple[PeakTableRecord, ...]:
        """Return the current immutable row snapshot."""

        return self._records

    @property
    def checked_records(self) -> tuple[PeakTableRecord, ...]:
        """Return the rows the operator kept for plotting and export."""

        return tuple(record for record in self._records if record.included)

    @property
    def sort_state(self) -> tuple[int, Qt.SortOrder]:
        """Return the active sort column and order, or ``(-1, Ascending)``."""

        return (self._sort_column, self._sort_order)

    def replace(self, records: Sequence[PeakTableRecord]) -> None:
        """Replace the current result snapshot while keeping the active order."""

        self.beginResetModel()
        self._records = self._sorted(records)
        self.endResetModel()

    def sort(  # noqa: N802
        self,
        column: int,
        order: Qt.SortOrder = Qt.SortOrder.AscendingOrder,
    ) -> None:
        """Reorder rows by one column; the checkbox column is not sortable."""

        if not 0 < column < len(self._HEADERS):
            return
        self._sort_column = column
        self._sort_order = order
        if not self._records:
            return
        self.beginResetModel()
        self._records = self._sorted(self._records)
        self.endResetModel()

    def _sorted(
        self,
        records: Sequence[PeakTableRecord],
    ) -> tuple[PeakTableRecord, ...]:
        rows = tuple(records)
        if self._sort_column < 0:
            return rows
        return tuple(
            sorted(
                rows,
                key=_peak_sort_key(self._sort_column),
                reverse=self._sort_order == Qt.SortOrder.DescendingOrder,
            )
        )

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._HEADERS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self._HEADERS)
        ):
            return self.tr(self._HEADERS[section])
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        if index.column() == 0:
            if role == Qt.ItemDataRole.CheckStateRole:
                return Qt.CheckState.Checked if record.included else Qt.CheckState.Unchecked
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return int(Qt.AlignmentFlag.AlignCenter)
            if role == Qt.ItemDataRole.ToolTipRole:
                return self.tr(
                    "Checked peaks are marked on the plot, copied, and exported. "
                    "Uncheck a peak to ignore it."
                )
            return None
        values: tuple[object, ...] = (
            record.sample_name,
            ", ".join(record.material_names),
            record.peak_number,
            f"{record.position_nm:.4f}",
            f"{record.height_au:.6g}",
            "—" if record.fwhm_nm is None else f"{record.fwhm_nm:.4f}",
            f"{record.prominence_au:.6g}",
            ", ".join(record.quality_flags),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column() - 1]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in self._NUMERIC_COLUMNS:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 6:
            return self.tr(
                "Raw half-prominence width in wavelength units. "
                "No fit or baseline correction is applied."
            )
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:  # noqa: N802
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or index.column() != 0
            or not index.isValid()
            or not 0 <= index.row() < len(self._records)
        ):
            return False
        check_state = normalize_check_state(value)
        if check_state is None:
            return False
        record = self._records[index.row()]
        included = check_state == Qt.CheckState.Checked
        if record.included == included:
            return False
        self._records = (
            *self._records[: index.row()],
            replace(record, included=included),
            *self._records[index.row() + 1 :],
        )
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.inclusion_changed.emit(record.spectrum_id, record.position_nm, included)
        return True

    def set_all_included(self, included: bool) -> None:
        """Check or uncheck every row in one operation."""

        rows = [row for row, record in enumerate(self._records) if record.included != included]
        if not rows:
            return
        updated = list(self._records)
        for row in rows:
            updated[row] = replace(updated[row], included=included)
        self._records = tuple(updated)
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._records) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole],
        )
        for row in rows:
            record = self._records[row]
            self.inclusion_changed.emit(record.spectrum_id, record.position_nm, included)

    def to_tsv(
        self,
        selected_rows: Sequence[int] | None = None,
        *,
        checked_only: bool = True,
    ) -> str:
        """Serialize the kept peaks as header-free, tab-separated clipboard text.

        Each line carries only the sample name, the peak position with its unit,
        and the peak height, so the paste is immediately usable in a report or a
        spreadsheet. There is no header row and no include/quality column.
        """

        row_indexes = (
            sorted(set(selected_rows)) if selected_rows else list(range(len(self._records)))
        )
        lines: list[str] = []
        for row_index in row_indexes:
            if not 0 <= row_index < len(self._records):
                continue
            record = self._records[row_index]
            if checked_only and not record.included:
                continue
            lines.append(
                "\t".join(
                    (
                        record.sample_name,
                        f"{record.position_nm:.4f} nm",
                        f"{record.height_au:.6g}",
                    )
                )
            )
        return "\n".join(lines)


class PeakPanel(QWidget):
    """Right-side multi-material windows and checkable raw peak results."""

    search_requested = Signal()
    copy_requested = Signal(str)
    export_requested = Signal()
    inclusion_changed = Signal(str, float, bool)
    invalid_window_selected = Signal(str)
    settings_changed = Signal()

    _INCLUDE_COLUMN_WIDTH = 44
    # Upper bounds keep nine columns readable inside a docked panel; the last
    # column ("Quality") stretches and every column stays user-resizable.
    _COLUMN_MAX_WIDTHS = {1: 130, 2: 150, 3: 44, 4: 80, 5: 80, 6: 80, 7: 96}

    def __init__(
        self,
        material_database: MaterialDatabase,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._material_model = MaterialWindowModel(material_database, self)
        self._material_model.invalid_window_selected.connect(self.invalid_window_selected.emit)
        self._material_model.settings_changed.connect(self.settings_changed.emit)
        material_table = QTableView(self)
        material_table.setModel(self._material_model)
        material_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        material_header = material_table.horizontalHeader()
        material_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        material_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        material_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        material_header.resizeSection(1, 78)
        material_header.resizeSection(2, 78)
        material_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        material_table.setMaximumHeight(210)

        select_all_button = QPushButton(self.tr("Select all defined"), self)
        select_all_button.clicked.connect(lambda: self._material_model.set_all_with_windows(True))
        clear_button = QPushButton(self.tr("Clear"), self)
        clear_button.clicked.connect(lambda: self._material_model.set_all_with_windows(False))
        material_buttons = QHBoxLayout()
        material_buttons.addWidget(select_all_button)
        material_buttons.addWidget(clear_button)
        material_buttons.addStretch(1)

        search_button = QPushButton(self.tr("Search selected material windows"), self)
        search_button.clicked.connect(self.search_requested)

        self._peak_model = PeakTableModel(self)
        self._peak_model.inclusion_changed.connect(self.inclusion_changed.emit)
        self._peak_table = QTableView(self)
        self._peak_table.setModel(self._peak_model)
        self._peak_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._peak_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._peak_table.setAlternatingRowColors(True)
        peak_header = self._peak_table.horizontalHeader()
        peak_header.setStretchLastSection(True)
        peak_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        peak_header.resizeSection(0, self._INCLUDE_COLUMN_WIDTH)
        peak_header.setSectionsClickable(True)
        peak_header.setSortIndicatorShown(False)
        peak_header.setToolTip(
            self.tr("Click a column header to sort ascending, click again for descending.")
        )
        peak_header.sectionClicked.connect(self._sort_peak_table)

        copy_button = QPushButton(self.tr("Copy checked"), self)
        copy_button.setToolTip(self.tr("Copy every checked peak as tab-separated text."))
        copy_button.clicked.connect(self._copy)
        export_button = QPushButton(self.tr("Export…"), self)
        export_button.clicked.connect(self.export_requested)
        check_all_button = QPushButton(self.tr("Check all"), self)
        check_all_button.clicked.connect(lambda: self._peak_model.set_all_included(True))
        uncheck_all_button = QPushButton(self.tr("Uncheck all"), self)
        uncheck_all_button.clicked.connect(lambda: self._peak_model.set_all_included(False))
        result_buttons = QHBoxLayout()
        result_buttons.addWidget(copy_button)
        result_buttons.addWidget(export_button)
        result_buttons.addWidget(check_all_button)
        result_buttons.addWidget(uncheck_all_button)
        result_buttons.addStretch(1)

        note = QLabel(
            self.tr(
                "Multiple material windows can be active together. Overlapping detections "
                "are shown once while retaining every material label. Raw FWHM is measured "
                "at half prominence without fitting or baseline correction. Only checked "
                "peaks are drawn, copied, and exported."
            ),
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #707070;")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Material Peak Windows"), self))
        layout.addWidget(material_table)
        layout.addLayout(material_buttons)
        layout.addWidget(search_button)
        layout.addSpacing(8)
        layout.addWidget(QLabel(self.tr("Raw Peak Table"), self))
        layout.addWidget(self._peak_table, 1)
        layout.addLayout(result_buttons)
        layout.addWidget(note)

    @property
    def search_windows(self) -> tuple[MaterialSearchWindow, ...]:
        """Return every checked material range."""

        return self._material_model.selected_windows()

    def material_window_snapshot(self) -> tuple[dict[str, object], ...]:
        """Return material window UI state for a project file."""

        return self._material_model.snapshot()

    def restore_material_windows(
        self,
        snapshots: Sequence[Mapping[str, object]],
    ) -> None:
        """Restore project-specific material selections and edits."""

        self._material_model.restore(snapshots)

    def set_records(self, records: Sequence[PeakTableRecord]) -> None:
        """Replace displayed peak results."""

        self._peak_model.replace(records)
        self._peak_table.resizeColumnsToContents()
        header = self._peak_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(0, self._INCLUDE_COLUMN_WIDTH)
        for column, maximum in self._COLUMN_MAX_WIDTHS.items():
            if header.sectionSize(column) > maximum:
                header.resizeSection(column, maximum)

    @property
    def checked_records(self) -> tuple[PeakTableRecord, ...]:
        """Return the peak rows the operator kept."""

        return self._peak_model.checked_records

    def _sort_peak_table(self, column: int) -> None:
        """Toggle ascending/descending order when a peak table header is clicked."""

        if column == 0:
            return
        header = self._peak_table.horizontalHeader()
        order = Qt.SortOrder.AscendingOrder
        if (
            header.sortIndicatorSection() == column
            and header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
        ):
            order = Qt.SortOrder.DescendingOrder
        self._peak_model.sort(column, order)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)

    def _copy(self) -> None:
        self.copy_requested.emit(self._peak_model.to_tsv())


def _valid_window(minimum: float | None, maximum: float | None) -> bool:
    return minimum is not None and maximum is not None and minimum > 0 and minimum < maximum


def _peak_sort_key(column: int) -> Callable[[PeakTableRecord], object]:
    """Return the value based sort key for one peak table column."""

    match column:
        case 1:
            return lambda record: record.sample_name.casefold()
        case 2:
            return lambda record: tuple(name.casefold() for name in record.material_names)
        case 3:
            return lambda record: record.peak_number
        case 4:
            return lambda record: record.position_nm
        case 5:
            return lambda record: record.height_au
        case 6:
            return lambda record: (record.fwhm_nm is None, record.fwhm_nm or 0.0)
        case 7:
            return lambda record: record.prominence_au
        case 8:
            return lambda record: tuple(flag.casefold() for flag in record.quality_flags)
        case _:
            return lambda record: record.position_nm
