"""Multi-material raw peak selection and tabular result presentation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
    """Read-only table model for de-duplicated, material-labelled raw peaks."""

    _HEADERS = (
        QT_TRANSLATE_NOOP("PeakTableModel", "Sample"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Material"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Peak"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Position\n(nm)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Height\n(a.u.)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "FWHM\n(nm)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Prominence\n(a.u.)"),
        QT_TRANSLATE_NOOP("PeakTableModel", "Quality"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: tuple[PeakTableRecord, ...] = ()

    @property
    def records(self) -> tuple[PeakTableRecord, ...]:
        """Return the current immutable row snapshot."""

        return self._records

    def replace(self, records: Sequence[PeakTableRecord]) -> None:
        """Replace the current result snapshot."""

        self.beginResetModel()
        self._records = tuple(records)
        self.endResetModel()

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
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {2, 3, 4, 5, 6}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.ToolTipRole and index.column() == 5:
            return self.tr(
                "Raw half-prominence width in wavelength units. "
                "No fit or baseline correction is applied."
            )
        return None

    def to_tsv(self, selected_rows: Sequence[int] | None = None) -> str:
        """Serialize selected or all rows for clipboard use."""

        row_indexes = (
            sorted(set(selected_rows)) if selected_rows else list(range(len(self._records)))
        )
        lines = ["\t".join(header.replace("\n", " ") for header in self._HEADERS)]
        for row_index in row_indexes:
            if not 0 <= row_index < len(self._records):
                continue
            record = self._records[row_index]
            lines.append(
                "\t".join(
                    (
                        record.sample_name,
                        ", ".join(record.material_names),
                        str(record.peak_number),
                        f"{record.position_nm:.8g}",
                        f"{record.height_au:.8g}",
                        "" if record.fwhm_nm is None else f"{record.fwhm_nm:.8g}",
                        f"{record.prominence_au:.8g}",
                        ", ".join(record.quality_flags),
                    )
                )
            )
        return "\n".join(lines)


class PeakPanel(QWidget):
    """Right-side multi-material windows and raw peak results."""

    search_requested = Signal()
    copy_requested = Signal(str)
    export_requested = Signal()
    invalid_window_selected = Signal(str)
    settings_changed = Signal()

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
        self._peak_table = QTableView(self)
        self._peak_table.setModel(self._peak_model)
        self._peak_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._peak_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._peak_table.setAlternatingRowColors(True)
        self._peak_table.horizontalHeader().setStretchLastSection(True)

        copy_button = QPushButton(self.tr("Copy"), self)
        copy_button.clicked.connect(self._copy)
        export_button = QPushButton(self.tr("Export…"), self)
        export_button.clicked.connect(self.export_requested)
        result_buttons = QHBoxLayout()
        result_buttons.addWidget(copy_button)
        result_buttons.addWidget(export_button)
        result_buttons.addStretch(1)

        note = QLabel(
            self.tr(
                "Multiple material windows can be active together. Overlapping detections "
                "are shown once while retaining every material label. Raw FWHM is measured "
                "at half prominence without fitting or baseline correction."
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

    def _copy(self) -> None:
        rows = [index.row() for index in self._peak_table.selectionModel().selectedRows()]
        self.copy_requested.emit(self._peak_model.to_tsv(rows))


def _valid_window(minimum: float | None, maximum: float | None) -> bool:
    return minimum is not None and maximum is not None and minimum > 0 and minimum < maximum
