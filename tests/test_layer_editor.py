"""Epitaxial Layer domain and editor-model behavior tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from core.models import PlotDisplaySettings
from core.project import Layer, PLProject
from core.workspace import Workspace
from ui.layer_editor import LayerDialog, LayerEditorWidget, LayerTableModel


def _layer(index: int) -> Layer:
    return Layer(
        layer_id=f"layer-{index}",
        material="GaAs" if index % 2 == 0 else "AlGaAs",
        thickness_nm=float(index + 1),
        composition="" if index % 2 == 0 else "Al=0.40",
        doping_type="Si" if index % 3 == 0 else "",
        doping_concentration_cm3=1.0e17 + index if index % 3 == 0 else None,
    )


def test_project_layer_stack_add_move_remove_and_identity() -> None:
    project = PLProject(workspace=Workspace(PlotDisplaySettings()))
    layers = [_layer(index) for index in range(128)]

    for layer in layers:
        project.add_layer(layer)

    assert len(project.layers) == 128
    assert project.layers[0].layer_id == "layer-0"
    assert project.layers[-1].layer_id == "layer-127"

    project.move_layer("layer-127", 0)
    assert project.layers[0] is layers[-1]
    assert project.layers[1] is layers[0]

    removed = project.remove_layer("layer-64")
    assert removed is layers[64]
    assert len(project.layers) == 127
    assert all(layer.layer_id != "layer-64" for layer in project.layers)

    with pytest.raises(ValueError, match="Duplicate layer ID"):
        project.add_layer(
            Layer(
                layer_id="layer-0",
                material="InP",
                thickness_nm=50.0,
            )
        )
    with pytest.raises(KeyError, match="Unknown layer ID"):
        project.remove_layer("not-present")


def test_layer_table_model_replaces_updates_reorders_and_removes(
    qapp: object,
) -> None:
    model = LayerTableModel()
    layers = [_layer(index) for index in range(64)]

    model.replace(layers)
    assert model.rowCount() == 64
    assert model.columnCount() == 6
    assert model.layers == tuple(layers)

    assert model.move(63, 0) is True
    assert model.layers[0].layer_id == "layer-63"
    assert model.move(0, 0) is False
    assert model.move(-1, 0) is False

    original_id = model.layers[10].layer_id
    replacement = Layer(
        layer_id=original_id,
        material="InP",
        thickness_nm=120.0,
        composition="-",
        doping_type="Zn",
        doping_concentration_cm3=2.5e17,
    )
    model.update_layer(10, replacement)
    assert model.layers[10] is replacement
    assert model.layers[10].layer_id == original_id

    model.remove(10)
    assert model.rowCount() == 63
    assert all(layer.layer_id != original_id for layer in model.layers)

    appended = Layer(material="InGaAs", thickness_nm=8.5)
    model.append(appended)
    assert model.rowCount() == 64
    assert model.layers[-1] is appended


def test_layer_editor_and_dialog_preserve_complete_layer_data(
    qtbot: pytest.FixtureRequest,
) -> None:
    layer = Layer(
        layer_id="stable-layer",
        material="AlGaAs",
        thickness_nm=400.0,
        composition="Al=0.40",
        doping_type="Si",
        doping_concentration_cm3=1.3e17,
    )
    editor = LayerEditorWidget()
    qtbot.addWidget(editor)

    editor.set_layers([layer])
    assert editor.layers == (layer,)

    dialog = LayerDialog(layer)
    qtbot.addWidget(dialog)
    rebuilt = dialog.layer()
    assert rebuilt.layer_id == "stable-layer"
    assert rebuilt.material == "AlGaAs"
    assert rebuilt.thickness_nm == pytest.approx(400.0)
    assert rebuilt.composition == "Al=0.40"
    assert rebuilt.doping_type == "Si"
    assert rebuilt.doping_concentration_cm3 == pytest.approx(1.3e17)
