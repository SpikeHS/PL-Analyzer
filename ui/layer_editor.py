"""Editable epitaxial layer stack for MBE project metadata."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QAbstractTableModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core.project import Layer


class LayerTableModel(QAbstractTableModel):
    """Read-only table adapter; edits are validated through ``LayerDialog``."""

    _HEADERS = (
        QT_TRANSLATE_NOOP("LayerTableModel", "Layer"),
        QT_TRANSLATE_NOOP("LayerTableModel", "Material"),
        QT_TRANSLATE_NOOP("LayerTableModel", "Thickness (nm)"),
        QT_TRANSLATE_NOOP("LayerTableModel", "Composition"),
        QT_TRANSLATE_NOOP("LayerTableModel", "Doping Type"),
        QT_TRANSLATE_NOOP("LayerTableModel", "Doping Concentration (cm⁻³)"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layers: list[Layer] = []

    @property
    def layers(self) -> tuple[Layer, ...]:
        """Return the current substrate-to-surface layer order."""

        return tuple(self._layers)

    def replace(self, layers: Sequence[Layer]) -> None:
        """Replace the complete stack."""

        self.beginResetModel()
        self._layers = list(layers)
        self.endResetModel()

    def append(self, layer: Layer) -> None:
        """Append a validated top layer."""

        row = len(self._layers)
        self.beginInsertRows(QModelIndex(), row, row)
        self._layers.append(layer)
        self.endInsertRows()

    def update_layer(self, row: int, layer: Layer) -> None:
        """Replace one layer while retaining its stable ID."""

        if not 0 <= row < len(self._layers):
            raise IndexError("Layer row is outside the stack.")
        self._layers[row] = layer
        self.dataChanged.emit(
            self.index(row, 0),
            self.index(row, self.columnCount() - 1),
        )

    def remove(self, row: int) -> None:
        """Remove one selected layer."""

        if not 0 <= row < len(self._layers):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        self._layers.pop(row)
        self.endRemoveRows()

    def move(self, source: int, destination: int) -> bool:
        """Move a layer in substrate-to-surface order."""

        if (
            not 0 <= source < len(self._layers)
            or not 0 <= destination < len(self._layers)
            or source == destination
        ):
            return False
        destination_child = destination + 1 if destination > source else destination
        self.beginMoveRows(
            QModelIndex(),
            source,
            source,
            QModelIndex(),
            destination_child,
        )
        layer = self._layers.pop(source)
        self._layers.insert(destination, layer)
        self.endMoveRows()
        self.dataChanged.emit(
            self.index(min(source, destination), 0),
            self.index(max(source, destination), 0),
        )
        return True

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        return 0 if parent is not None and parent.isValid() else len(self._layers)

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
        if not index.isValid() or not 0 <= index.row() < len(self._layers):
            return None
        layer = self._layers[index.row()]
        concentration = (
            "—"
            if layer.doping_concentration_cm3 is None
            else f"{layer.doping_concentration_cm3:.4g}"
        )
        values: tuple[object, ...] = (
            self.tr("Layer {number}").format(number=index.row() + 1),
            layer.material,
            f"{layer.thickness_nm:.6g}",
            layer.composition or "—",
            layer.doping_type or "—",
            concentration,
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in {0, 2, 5}:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class LayerEditorWidget(QWidget):
    """Full Layer Editor with unlimited rows and explicit order controls."""

    layers_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = LayerTableModel(self)
        self._table = QTableView(self)
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.doubleClicked.connect(self._edit_selected)

        add_button = QPushButton(self.tr("Add layer…"), self)
        add_button.clicked.connect(self._add_layer)
        edit_button = QPushButton(self.tr("Edit…"), self)
        edit_button.clicked.connect(self._edit_selected)
        remove_button = QPushButton(self.tr("Remove"), self)
        remove_button.clicked.connect(self._remove_selected)
        up_button = QPushButton(self.tr("Move up"), self)
        up_button.clicked.connect(lambda: self._move_selected(-1))
        down_button = QPushButton(self.tr("Move down"), self)
        down_button.clicked.connect(lambda: self._move_selected(1))

        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(edit_button)
        buttons.addWidget(remove_button)
        buttons.addSpacing(16)
        buttons.addWidget(up_button)
        buttons.addWidget(down_button)
        buttons.addStretch(1)

        heading = QLabel(self.tr("Epitaxial Layer Editor"), self)
        heading.setStyleSheet("font-size: 16px; font-weight: 600;")
        description = QLabel(
            self.tr(
                "Order is substrate side → surface side. Double-click a row to edit. "
                "The stack has no software layer-count limit."
            ),
            self,
        )
        description.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addLayout(buttons)
        layout.addWidget(self._table, 1)

    @property
    def layers(self) -> tuple[Layer, ...]:
        """Return the current validated layer stack."""

        return self._model.layers

    def set_layers(self, layers: Sequence[Layer]) -> None:
        """Replace the current layer stack."""

        self._model.replace(layers)
        self._table.resizeColumnsToContents()

    def _selected_row(self) -> int | None:
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _add_layer(self) -> None:
        dialog = LayerDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._model.append(dialog.layer())
        row = self._model.rowCount() - 1
        self._table.selectRow(row)
        self._table.resizeColumnsToContents()
        self.layers_changed.emit()

    def _edit_selected(self, _index: QModelIndex | None = None) -> None:
        row = self._selected_row()
        if row is None:
            return
        current = self._model.layers[row]
        dialog = LayerDialog(current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._model.update_layer(row, dialog.layer())
        self._table.resizeColumnsToContents()
        self.layers_changed.emit()

    def _remove_selected(self) -> None:
        row = self._selected_row()
        if row is None:
            return
        layer = self._model.layers[row]
        answer = QMessageBox.question(
            self,
            self.tr("Remove layer"),
            self.tr("Remove Layer {number} ({material})?").format(
                number=row + 1,
                material=layer.material,
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._model.remove(row)
        self.layers_changed.emit()

    def _move_selected(self, delta: int) -> None:
        row = self._selected_row()
        if row is None:
            return
        destination = row + delta
        if self._model.move(row, destination):
            self._table.selectRow(destination)
            self.layers_changed.emit()


class LayerDialog(QDialog):
    """Validated add/edit dialog for one epitaxial layer."""

    def __init__(
        self,
        layer: Layer | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._source_layer = layer
        self.setWindowTitle(
            self.tr("Edit epitaxial layer") if layer else self.tr("Add epitaxial layer")
        )

        self._material = QLineEdit(layer.material if layer else "GaAs", self)
        self._thickness = QDoubleSpinBox(self)
        self._thickness.setRange(0.000001, 1.0e9)
        self._thickness.setDecimals(6)
        self._thickness.setValue(layer.thickness_nm if layer else 1.0)
        self._thickness.setSuffix(" nm")
        self._composition = QLineEdit(layer.composition if layer else "", self)
        self._composition.setPlaceholderText(self.tr("e.g. Al=0.40 or —"))
        self._doping_type = QComboBox(self)
        self._doping_type.setEditable(True)
        self._doping_type.addItems(["", "Si", "Be", "C", "Zn", "Te", "Sn"])
        self._doping_type.setCurrentText(layer.doping_type if layer else "")
        self._concentration = QLineEdit(self)
        self._concentration.setPlaceholderText(self.tr("e.g. 1.3E17; blank for undoped"))
        if layer and layer.doping_concentration_cm3 is not None:
            self._concentration.setText(f"{layer.doping_concentration_cm3:.8g}")

        form = QFormLayout()
        form.addRow(self.tr("Material"), self._material)
        form.addRow(self.tr("Thickness"), self._thickness)
        form.addRow(self.tr("Composition"), self._composition)
        form.addRow(self.tr("Doping type"), self._doping_type)
        form.addRow(self.tr("Concentration (cm⁻³)"), self._concentration)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def layer(self) -> Layer:
        """Build the validated layer represented by the dialog."""

        concentration_text = self._concentration.text().strip()
        concentration = float(concentration_text) if concentration_text else None
        return Layer(
            layer_id=(
                self._source_layer.layer_id
                if self._source_layer is not None
                else Layer(
                    material=self._material.text(),
                    thickness_nm=self._thickness.value(),
                ).layer_id
            ),
            material=self._material.text(),
            thickness_nm=self._thickness.value(),
            composition=self._composition.text(),
            doping_type=self._doping_type.currentText(),
            doping_concentration_cm3=concentration,
        )

    def _validate_and_accept(self) -> None:
        try:
            self.layer()
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, self.tr("Invalid layer"), str(exc))
            return
        self.accept()
