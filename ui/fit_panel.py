"""v1.1 fit controls and fitted-peak result table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from analysis.fit_session import FitTableRecord
from analysis.fitting import BaselineMode, FitModel


@dataclass(frozen=True, slots=True)
class FitUiSettings:
    """Operator fit controls independent of any one material window."""

    model: FitModel
    baseline: BaselineMode
    peak_count: int | Literal["auto"]
    max_peaks: int
    savgol_enabled: bool
    savgol_window_length: int
    savgol_polyorder: int
    min_peak_distance_nm: float


class FitTableModel(QAbstractTableModel):
    """Read-only metrics from successful material-window fits."""

    _HEADERS = (
        "Sample",
        "Material",
        "Model",
        "Peak",
        "Position\n(nm)",
        "Height\n(a.u.)",
        "Area\n(a.u.·nm)",
        "FWHM\n(nm)",
        "R²",
        "Adj. R²",
        "AIC",
        "BIC",
        "Baseline",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: tuple[FitTableRecord, ...] = ()

    def replace(self, records: Sequence[FitTableRecord]) -> None:
        """Replace fitted result rows."""

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
            return self._HEADERS[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._records):
            return None
        record = self._records[index.row()]
        values: tuple[object, ...] = (
            record.sample_name,
            record.material_name,
            record.model.value,
            record.peak_number,
            f"{record.position_nm:.5f}",
            f"{record.height_au:.7g}",
            f"{record.area_au_nm:.7g}",
            f"{record.fwhm_nm:.5f}",
            f"{record.r_squared:.6f}",
            ("—" if record.adjusted_r_squared is None else f"{record.adjusted_r_squared:.6f}"),
            f"{record.aic:.6g}",
            f"{record.bic:.6g}",
            record.baseline_mode.value,
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() >= 3:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def to_tsv(self, selected_rows: Sequence[int] | None = None) -> str:
        """Serialize selected or all rows for clipboard use."""

        rows = sorted(set(selected_rows)) if selected_rows else list(range(len(self._records)))
        lines = ["\t".join(header.replace("\n", " ") for header in self._HEADERS)]
        for row in rows:
            if not 0 <= row < len(self._records):
                continue
            record = self._records[row]
            lines.append(
                "\t".join(
                    (
                        record.sample_name,
                        record.material_name,
                        record.model.value,
                        str(record.peak_number),
                        f"{record.position_nm:.9g}",
                        f"{record.height_au:.9g}",
                        f"{record.area_au_nm:.9g}",
                        f"{record.fwhm_nm:.9g}",
                        f"{record.r_squared:.9g}",
                        (
                            ""
                            if record.adjusted_r_squared is None
                            else f"{record.adjusted_r_squared:.9g}"
                        ),
                        f"{record.aic:.9g}",
                        f"{record.bic:.9g}",
                        record.baseline_mode.value,
                    )
                )
            )
        return "\n".join(lines)


class FitPanel(QWidget):
    """Fit setup and table; material windows come from the Raw Peak tab."""

    fit_requested = Signal()
    copy_requested = Signal(str)
    export_requested = Signal()
    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_combo = QComboBox(self)
        for model in FitModel:
            self._model_combo.addItem(
                model.value.replace("_", " ").title(),
                model.value,
            )

        self._baseline_combo = QComboBox(self)
        for baseline in BaselineMode:
            self._baseline_combo.addItem(baseline.value.title(), baseline.value)
        self._baseline_combo.setCurrentIndex(
            self._baseline_combo.findData(BaselineMode.LINEAR.value)
        )

        self._peak_count_combo = QComboBox(self)
        self._peak_count_combo.addItem("Auto", "auto")
        for count in range(1, 7):
            self._peak_count_combo.addItem(str(count), count)

        self._max_peaks = QSpinBox(self)
        self._max_peaks.setRange(1, 20)
        self._max_peaks.setValue(3)
        self._minimum_distance = QDoubleSpinBox(self)
        self._minimum_distance.setRange(0.0, 100000.0)
        self._minimum_distance.setDecimals(4)
        self._minimum_distance.setSuffix(" nm")

        self._savgol_enabled = QCheckBox("Enable", self)
        self._savgol_window = QSpinBox(self)
        self._savgol_window.setRange(3, 999)
        self._savgol_window.setSingleStep(2)
        self._savgol_window.setValue(11)
        self._savgol_window.editingFinished.connect(self._ensure_odd_savgol_window)
        self._savgol_polyorder = QSpinBox(self)
        self._savgol_polyorder.setRange(0, 9)
        self._savgol_polyorder.setValue(3)
        self._savgol_window.valueChanged.connect(self._update_savgol_polyorder_limit)

        self._model_combo.currentIndexChanged.connect(self.settings_changed.emit)
        self._baseline_combo.currentIndexChanged.connect(self.settings_changed.emit)
        self._peak_count_combo.currentIndexChanged.connect(self.settings_changed.emit)
        self._max_peaks.valueChanged.connect(self.settings_changed.emit)
        self._minimum_distance.valueChanged.connect(self.settings_changed.emit)
        self._savgol_enabled.toggled.connect(self.settings_changed.emit)
        self._savgol_window.valueChanged.connect(self.settings_changed.emit)
        self._savgol_polyorder.valueChanged.connect(self.settings_changed.emit)

        form = QFormLayout()
        form.addRow("Line shape", self._model_combo)
        form.addRow("Baseline", self._baseline_combo)
        form.addRow("Peak count", self._peak_count_combo)
        form.addRow("Auto max peaks", self._max_peaks)
        form.addRow("Minimum distance", self._minimum_distance)
        form.addRow("Savitzky-Golay", self._savgol_enabled)
        form.addRow("SG window (odd)", self._savgol_window)
        form.addRow("SG polynomial", self._savgol_polyorder)

        fit_button = QPushButton("Fit selected material windows", self)
        fit_button.clicked.connect(self.fit_requested)

        self._table_model = FitTableModel(self)
        self._table = QTableView(self)
        self._table.setModel(self._table_model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setAlternatingRowColors(True)

        copy_button = QPushButton("Copy", self)
        copy_button.clicked.connect(self._copy)
        export_button = QPushButton("Export…", self)
        export_button.clicked.connect(self.export_requested)
        buttons = QHBoxLayout()
        buttons.addWidget(copy_button)
        buttons.addWidget(export_button)
        buttons.addStretch(1)

        note = QLabel(
            "Auto evaluates Gaussian, Lorentzian, Voigt and Pseudo-Voigt candidates "
            "and selects by BIC. Fits always use raw linear intensity inside the "
            "material windows selected on the Raw Peak tab.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #707070;")

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("v1.1 Model Fit", self))
        layout.addLayout(form)
        layout.addWidget(fit_button)
        layout.addWidget(QLabel("Fit Results", self))
        layout.addWidget(self._table, 1)
        layout.addLayout(buttons)
        layout.addWidget(note)

    @property
    def settings(self) -> FitUiSettings:
        """Return current fit controls."""

        peak_count = self._peak_count_combo.currentData()
        return FitUiSettings(
            model=FitModel(str(self._model_combo.currentData())),
            baseline=BaselineMode(str(self._baseline_combo.currentData())),
            peak_count=peak_count,
            max_peaks=self._max_peaks.value(),
            savgol_enabled=self._savgol_enabled.isChecked(),
            savgol_window_length=self._savgol_window.value(),
            savgol_polyorder=self._savgol_polyorder.value(),
            min_peak_distance_nm=self._minimum_distance.value(),
        )

    def set_records(self, records: Sequence[FitTableRecord]) -> None:
        """Replace fit table rows."""

        self._table_model.replace(records)
        self._table.resizeColumnsToContents()

    def settings_snapshot(self) -> dict[str, object]:
        """Return JSON-ready fit controls for project persistence."""

        settings = self.settings
        return {
            "model": settings.model.value,
            "baseline": settings.baseline.value,
            "peak_count": settings.peak_count,
            "max_peaks": settings.max_peaks,
            "savgol_enabled": settings.savgol_enabled,
            "savgol_window_length": settings.savgol_window_length,
            "savgol_polyorder": settings.savgol_polyorder,
            "min_peak_distance_nm": settings.min_peak_distance_nm,
        }

    def restore_settings(self, snapshot: Mapping[str, object]) -> None:
        """Restore a validated project snapshot without emitting change events."""

        try:
            model = FitModel(str(snapshot["model"]))
            baseline = BaselineMode(str(snapshot["baseline"]))
            peak_count_value = snapshot["peak_count"]
            peak_count: int | Literal["auto"]
            peak_count = "auto" if peak_count_value == "auto" else int(peak_count_value)
            candidate = FitUiSettings(
                model=model,
                baseline=baseline,
                peak_count=peak_count,
                max_peaks=int(snapshot["max_peaks"]),
                savgol_enabled=bool(snapshot["savgol_enabled"]),
                savgol_window_length=int(snapshot["savgol_window_length"]),
                savgol_polyorder=int(snapshot["savgol_polyorder"]),
                min_peak_distance_nm=float(snapshot["min_peak_distance_nm"]),
            )
            if (
                candidate.max_peaks < 1
                or candidate.max_peaks > 20
                or (candidate.peak_count != "auto" and not 1 <= candidate.peak_count <= 6)
                or candidate.savgol_window_length < 3
                or candidate.savgol_window_length % 2 == 0
                or candidate.savgol_window_length > 999
                or candidate.savgol_polyorder < 0
                or candidate.savgol_polyorder >= candidate.savgol_window_length
                or candidate.min_peak_distance_nm < 0
            ):
                return
        except (KeyError, TypeError, ValueError):
            return

        widgets = (
            self._model_combo,
            self._baseline_combo,
            self._peak_count_combo,
            self._max_peaks,
            self._minimum_distance,
            self._savgol_enabled,
            self._savgol_window,
            self._savgol_polyorder,
        )
        previous_states = [widget.blockSignals(True) for widget in widgets]
        try:
            self._model_combo.setCurrentIndex(self._model_combo.findData(candidate.model.value))
            self._baseline_combo.setCurrentIndex(
                self._baseline_combo.findData(candidate.baseline.value)
            )
            self._peak_count_combo.setCurrentIndex(
                self._peak_count_combo.findData(candidate.peak_count)
            )
            self._max_peaks.setValue(candidate.max_peaks)
            self._minimum_distance.setValue(candidate.min_peak_distance_nm)
            self._savgol_enabled.setChecked(candidate.savgol_enabled)
            self._savgol_window.setValue(candidate.savgol_window_length)
            self._update_savgol_polyorder_limit(candidate.savgol_window_length)
            self._savgol_polyorder.setValue(candidate.savgol_polyorder)
        finally:
            for widget, previous_state in zip(
                widgets,
                previous_states,
                strict=True,
            ):
                widget.blockSignals(previous_state)

    def _ensure_odd_savgol_window(self) -> None:
        value = self._savgol_window.value()
        if value % 2 == 0:
            self._savgol_window.setValue(min(value + 1, 999))

    def _update_savgol_polyorder_limit(self, window_length: int) -> None:
        self._savgol_polyorder.setMaximum(min(9, window_length - 1))

    def _copy(self) -> None:
        rows = [index.row() for index in self._table.selectionModel().selectedRows()]
        self.copy_requested.emit(self._table_model.to_tsv(rows))
