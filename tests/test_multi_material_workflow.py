"""Multi-material selection and overlapping Raw Peak workflow tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from analysis.raw_peak import RawPeakAnalyzer, RawPeakConfig
from core.configuration import MaterialDatabase, application_root
from core.models import (
    MaterialPeakAnalysis,
    MaterialSearchWindow,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.persistence import ProjectPersistence
from core.project import MaterialWindowSnapshot, PLProject
from core.workspace import Workspace
from ui.peak_panel import MaterialWindowModel


def test_multiple_material_windows_can_be_selected_together(
    qapp: object,
) -> None:
    """Checked material rows must form one multi-window analysis request."""

    database = MaterialDatabase.from_json(application_root() / "config" / "materials.json")
    model = MaterialWindowModel(database)

    assert [window.material_id for window in model.selected_windows()] == [
        "gaas_300k",
        "algaas_al040_300k",
    ]

    inp_row = next(
        index
        for index, material in enumerate(database.materials)
        if material.material_id == "inp_300k"
    )
    changed = model.setData(
        model.index(inp_row, 0),
        Qt.CheckState.Checked,
        Qt.ItemDataRole.CheckStateRole,
    )

    assert changed is True
    selected = model.selected_windows()
    assert [window.material_id for window in selected] == [
        "gaas_300k",
        "algaas_al040_300k",
        "inp_300k",
    ]
    assert [(window.min_nm, window.max_nm) for window in selected] == [
        (860.0, 900.0),
        (620.0, 670.0),
        (890.0, 970.0),
    ]


def test_material_window_accepts_qt_unchecked_enum(qapp: object) -> None:
    """Unchecking a selected material must accept PySide6's CheckState enum."""

    database = MaterialDatabase.from_json(application_root() / "config" / "materials.json")
    model = MaterialWindowModel(database)
    gaas_row = next(
        index
        for index, material in enumerate(database.materials)
        if material.material_id == "gaas_300k"
    )

    changed = model.setData(
        model.index(gaas_row, 0),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )

    assert changed is True
    assert "gaas_300k" not in {window.material_id for window in model.selected_windows()}


def test_v1_custom_material_windows_restore_into_current_ui_rows(
    qapp: object,
    tmp_path: Path,
) -> None:
    """Legacy IDs must retain operator selection and range edits in the UI."""

    target = tmp_path / "legacy-window-state.plproj"
    project = PLProject(
        workspace=Workspace(PlotDisplaySettings()),
        material_windows=[
            MaterialWindowSnapshot(
                "gaas",
                "GaAs",
                862.5,
                897.5,
                selected=False,
            ),
            MaterialWindowSnapshot(
                "algaas_al040",
                "AlGaAs",
                624.0,
                666.0,
                selected=True,
            ),
        ],
    )
    persistence = ProjectPersistence()
    persistence.save(project, target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    target.write_text(json.dumps(payload), encoding="utf-8")

    restored = persistence.load(target)
    database = MaterialDatabase.from_json(application_root() / "config" / "materials.json")
    model = MaterialWindowModel(database)
    model.restore(
        [
            {
                "material_id": window.material_id,
                "selected": window.selected,
                "min_nm": window.minimum_nm,
                "max_nm": window.maximum_nm,
            }
            for window in restored.material_windows
        ]
    )
    by_id = {str(snapshot["material_id"]): snapshot for snapshot in model.snapshot()}

    assert by_id["gaas_300k"] == {
        "material_id": "gaas_300k",
        "display_name": "GaAs (300 K)",
        "selected": False,
        "min_nm": 862.5,
        "max_nm": 897.5,
    }
    assert by_id["algaas_al040_300k"] == {
        "material_id": "algaas_al040_300k",
        "display_name": "Al₀.₄Ga₀.₆As (300 K)",
        "selected": True,
        "min_nm": 624.0,
        "max_nm": 666.0,
    }


def test_overlapping_windows_deduplicate_peak_and_keep_all_material_labels() -> None:
    """One sampled physical peak is one row even when two windows detect it."""

    wavelength_nm = np.linspace(840.0, 920.0, 321)
    intensity_au = 2.0 + 75.0 * np.exp(-4.0 * np.log(2.0) * ((wavelength_nm - 875.0) / 6.0) ** 2)
    spectrum = SpectrumSeries(
        spectrum_id="overlap",
        name="AGA-overlap",
        wavelength_nm=wavelength_nm,
        intensity_au=intensity_au,
        source=SourceInfo(
            file_path="C:/data/overlap.csv",
            sheet_name=None,
            wavelength_column="Wavelength",
            intensity_column="Intensity",
        ),
    )
    windows = (
        MaterialSearchWindow(
            material_id="gaas_candidate",
            material_name="GaAs candidate",
            min_nm=860.0,
            max_nm=890.0,
        ),
        MaterialSearchWindow(
            material_id="broad_candidate",
            material_name="Overlapping candidate",
            min_nm=850.0,
            max_nm=900.0,
        ),
    )
    analyzer = RawPeakAnalyzer()
    analyses = tuple(
        MaterialPeakAnalysis(
            window=window,
            result=analyzer.analyze_spectrum(
                spectrum,
                RawPeakConfig(
                    search_min_nm=window.min_nm,
                    search_max_nm=window.max_nm,
                    relative_prominence=0.01,
                    noise_sigma_factor=0.0,
                    min_distance_nm=0.0,
                    max_peaks=5,
                    gap_factor=10.0,
                ),
            ),
        )
        for window in windows
    )
    assert [len(analysis.result.peaks) for analysis in analyses] == [1, 1]
    assert analyses[0].result.peaks[0].position_nm == pytest.approx(875.0)
    assert analyses[1].result.peaks[0].position_nm == pytest.approx(875.0)

    workspace = Workspace(PlotDisplaySettings())
    workspace.add_spectra([spectrum])
    workspace.set_material_peak_results({"overlap": analyses})

    assert len(workspace.material_peak_results["overlap"]) == 2
    assert len(workspace.peak_results["overlap"].peaks) == 1
    records = workspace.peak_table_records()
    assert len(records) == 1
    assert records[0].position_nm == pytest.approx(875.0)
    assert records[0].material_names == (
        "GaAs candidate",
        "Overlapping candidate",
    )
    assert "AMBIGUOUS_MATERIAL_ASSIGNMENT" in records[0].quality_flags
