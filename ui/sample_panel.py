"""Checkable sample list for multi-spectrum comparison."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.models import SpectrumSeries
from ui.qt_compat import normalize_check_state


class SampleListModel(QAbstractListModel):
    """Qt adapter over workspace spectra using stable spectrum IDs."""

    visibility_changed = Signal(str, bool)
    spectrum_id_role = int(Qt.ItemDataRole.UserRole) + 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spectra: list[SpectrumSeries] = []

    def replace(self, spectra: Sequence[SpectrumSeries]) -> None:
        """Reset the view after a workspace-level collection change."""

        self.beginResetModel()
        self._spectra = list(spectra)
        self.endResetModel()

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._spectra)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._spectra):
            return None
        spectrum = self._spectra[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return spectrum.name
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if spectrum.display.visible else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole:
            return QColor(spectrum.display.color)
        if role == Qt.ItemDataRole.ToolTipRole:
            sheet = spectrum.source.sheet_name or self.tr("CSV")
            return self.tr(
                "{file_path}\nSheet: {sheet}\nColumns: {wavelength_column} / {intensity_column}"
            ).format(
                file_path=spectrum.source.file_path,
                sheet=sheet,
                wavelength_column=spectrum.source.wavelength_column,
                intensity_column=spectrum.source.intensity_column,
            )
        if role == self.spectrum_id_role:
            return spectrum.spectrum_id
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )

    def setData(
        self,
        index: QModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:  # noqa: N802
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or not index.isValid()
            or not 0 <= index.row() < len(self._spectra)
        ):
            return False
        spectrum = self._spectra[index.row()]
        check_state = normalize_check_state(value)
        if check_state is None:
            return False
        visible = check_state == Qt.CheckState.Checked
        if spectrum.display.visible == visible:
            return False
        spectrum.display.visible = visible
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.visibility_changed.emit(spectrum.spectrum_id, visible)
        return True


class SamplePanel(QWidget):
    """Left-side sample visibility and removal controls."""

    visibility_changed = Signal(str, bool)
    remove_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = SampleListModel(self)
        self._model.visibility_changed.connect(self.visibility_changed.emit)
        self._view = QListView(self)
        self._view.setModel(self._model)
        self._view.setSelectionMode(QListView.SelectionMode.ExtendedSelection)

        import_hint = QLabel(
            self.tr("Drop CSV/XLSX/XLS files here or use File → Open."),
            self,
        )
        import_hint.setWordWrap(True)
        import_hint.setStyleSheet("color: #707070;")

        remove_button = QPushButton(self.tr("Remove selected"), self)
        remove_button.clicked.connect(self._request_removal)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.tr("Samples"), self))
        layout.addWidget(self._view, 1)
        layout.addWidget(import_hint)
        layout.addLayout(button_row)

    def set_spectra(self, spectra: Sequence[SpectrumSeries]) -> None:
        """Replace displayed samples."""

        self._model.replace(spectra)

    def _request_removal(self) -> None:
        selected_ids = tuple(
            str(index.data(SampleListModel.spectrum_id_role))
            for index in self._view.selectionModel().selectedIndexes()
        )
        if selected_ids:
            self.remove_requested.emit(selected_ids)
