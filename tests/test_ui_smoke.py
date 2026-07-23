"""Headless construction test for the complete desktop composition."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("matplotlib")

from analysis.raw_peak import RawPeakAnalyzer
from core.configuration import ApplicationSettings, MaterialDatabase, application_root
from core.importing.service import SpectrumImportService
from core.models import SourceInfo, SpectrumSeries
from core.workspace import Workspace
from export.peak_table import PeakTableExporter
from ui.fit_panel import FitPanel
from ui.main_window import MainWindow


def test_main_window_constructs_offscreen(qtbot: pytest.FixtureRequest) -> None:
    root = application_root()
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")
    window = MainWindow(
        workspace=Workspace(settings.plot),
        importer=SpectrumImportService(),
        analyzer=RawPeakAnalyzer(),
        exporter=PeakTableExporter(),
        material_database=materials,
        analysis_defaults=settings.analysis,
    )
    qtbot.addWidget(window)

    assert window.windowTitle() == "Untitled — PL Analyzer Pro v1.1"


def test_fit_panel_settings_round_trip(qtbot: pytest.FixtureRequest) -> None:
    panel = FitPanel()
    qtbot.addWidget(panel)
    snapshot = {
        "model": "pseudo_voigt",
        "baseline": "constant",
        "peak_count": 2,
        "max_peaks": 4,
        "savgol_enabled": True,
        "savgol_window_length": 9,
        "savgol_polyorder": 2,
        "min_peak_distance_nm": 1.25,
    }

    panel.restore_settings(snapshot)

    assert panel.settings_snapshot() == snapshot


def test_main_window_runs_selected_material_fits(
    qtbot: pytest.FixtureRequest,
) -> None:
    root = application_root()
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")
    workspace = Workspace(settings.plot)
    wavelength_nm = np.linspace(600.0, 910.0, 1000)
    intensity_au = 5.0 + 0.003 * (wavelength_nm - 750.0)
    intensity_au += 40.0 * np.exp(-4.0 * np.log(2.0) * ((wavelength_nm - 645.0) / 12.0) ** 2)
    intensity_au += 70.0 * np.exp(-4.0 * np.log(2.0) * ((wavelength_nm - 875.0) / 16.0) ** 2)
    workspace.add_spectra(
        (
            SpectrumSeries(
                spectrum_id="ui-fit",
                name="AGA UI Fit",
                wavelength_nm=wavelength_nm,
                intensity_au=intensity_au,
                source=SourceInfo(
                    file_path="ui-fit.csv",
                    sheet_name=None,
                    wavelength_column="Wavelength",
                    intensity_column="Intensity",
                ),
            ),
        )
    )
    window = MainWindow(
        workspace=workspace,
        importer=SpectrumImportService(),
        analyzer=RawPeakAnalyzer(),
        exporter=PeakTableExporter(),
        material_database=materials,
        analysis_defaults=settings.analysis,
    )
    qtbot.addWidget(window)
    window._fit_panel.restore_settings(
        {
            "model": "gaussian",
            "baseline": "linear",
            "peak_count": 1,
            "max_peaks": 1,
            "savgol_enabled": False,
            "savgol_window_length": 11,
            "savgol_polyorder": 3,
            "min_peak_distance_nm": 0.0,
        }
    )

    window._run_fit(show_summary=False)

    assignments = window._fit_store.assignments
    assert len(assignments) == 2
    assert {assignment.window.material_id for assignment in assignments} == {
        "gaas_300k",
        "algaas_al040_300k",
    }
    assert all(len(assignment.result.peaks) == 1 for assignment in assignments)
    assert all(assignment.result.r_squared > 0.999 for assignment in assignments)
    window._set_dirty(False)
