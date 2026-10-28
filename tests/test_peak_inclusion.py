"""Checked/ignored raw peak tests across workspace, table model, and projects."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from analysis.raw_peak import RawPeakAnalyzer
from core.configuration import ApplicationSettings, MaterialDatabase, application_root
from core.importing.service import SpectrumImportService
from core.models import (
    MaterialPeakAnalysis,
    MaterialSearchWindow,
    PeakAnalysisResult,
    PeakResult,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.workspace import Workspace
from export.peak_table import PeakTableExporter
from ui.main_window import MainWindow
from ui.peak_panel import PeakPanel, PeakTableModel
from ui.sample_panel import SamplePanel


def _spectrum(
    identifier: str = "AGA017",
    name: str = "AGA017",
    *,
    wavelength_nm: tuple[float, ...] = (860.0, 870.0, 880.0),
    intensity_au: tuple[float, ...] = (1.0, 5.0, 1.0),
) -> SpectrumSeries:
    return SpectrumSeries(
        spectrum_id=identifier,
        name=name,
        wavelength_nm=np.asarray(wavelength_nm),
        intensity_au=np.asarray(intensity_au),
        source=SourceInfo(
            file_path=f"C:/{name}.opj",
            sheet_name=None,
            wavelength_column="Wavelength",
            intensity_column="Intensity",
        ),
    )


def _two_peak_result() -> PeakAnalysisResult:
    return PeakAnalysisResult(
        peaks=(
            PeakResult(
                position_nm=870.0,
                height_au=5.0,
                fwhm_nm=8.0,
                prominence_au=4.0,
                width_level_au=3.0,
            ),
            PeakResult(
                position_nm=875.0,
                height_au=3.0,
                fwhm_nm=6.0,
                prominence_au=2.0,
                width_level_au=2.0,
            ),
        ),
        effective_prominence_au=0.1,
        diagnostics=(),
    )


def _workspace_with_two_peaks() -> Workspace:
    workspace = Workspace(PlotDisplaySettings())
    workspace.add_spectra([_spectrum()])
    workspace.set_material_peak_results(
        {
            "AGA017": (
                MaterialPeakAnalysis(
                    window=MaterialSearchWindow(
                        material_id="gaas_300k",
                        material_name="GaAs",
                        min_nm=860.0,
                        max_nm=880.0,
                    ),
                    result=_two_peak_result(),
                ),
            )
        }
    )
    return workspace


def test_ignoring_a_peak_removes_it_from_plot_markers_and_marks_the_record() -> None:
    workspace = _workspace_with_two_peaks()
    assert [peak.position_nm for peak in workspace.peak_results["AGA017"].peaks] == [
        870.0,
        875.0,
    ]

    assert workspace.set_peak_included("AGA017", 870.0, False) is True
    assert workspace.set_peak_included("AGA017", 870.0, False) is False
    assert workspace.peak_included("AGA017", 870.0) is False

    assert [peak.position_nm for peak in workspace.peak_results["AGA017"].peaks] == [875.0]
    records = workspace.peak_table_records()
    assert [(record.position_nm, record.included) for record in records] == [
        (870.0, False),
        (875.0, True),
    ]
    assert records[0].spectrum_id == "AGA017"

    assert workspace.set_peak_included("AGA017", 870.0, True) is True
    assert len(workspace.peak_results["AGA017"].peaks) == 2


def test_ignore_decisions_survive_reanalysis_and_drop_with_the_sample() -> None:
    workspace = _workspace_with_two_peaks()
    workspace.set_peak_included("AGA017", 870.0, False)

    workspace.clear_peak_results()
    workspace.set_material_peak_results(
        {
            "AGA017": (
                MaterialPeakAnalysis(
                    window=MaterialSearchWindow(
                        material_id="gaas_300k",
                        material_name="GaAs",
                        min_nm=860.0,
                        max_nm=880.0,
                    ),
                    result=_two_peak_result(),
                ),
            )
        }
    )

    records = workspace.peak_table_records()
    assert [record.included for record in records] == [False, True]
    assert workspace.ignored_peaks == (("AGA017", 870.0),)

    workspace.remove_spectra(["AGA017"])

    assert workspace.ignored_peaks == ()


def test_unknown_spectrum_cannot_receive_a_peak_decision() -> None:
    workspace = _workspace_with_two_peaks()

    with pytest.raises(KeyError):
        workspace.set_peak_included("missing", 870.0, False)


def test_peak_table_model_toggles_inclusion_and_copies_checked_rows(
    qapp: object,
) -> None:
    workspace = _workspace_with_two_peaks()
    model = PeakTableModel()
    model.replace(workspace.peak_table_records())
    changes: list[tuple[str, float, bool]] = []
    model.inclusion_changed.connect(
        lambda spectrum_id, position, included: changes.append((spectrum_id, position, included))
    )

    assert model.headerData(0, Qt.Orientation.Horizontal) == "Include"
    assert model.columnCount() == 9
    index = model.index(0, 0)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked

    assert model.setData(index, Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    assert changes == [("AGA017", 870.0, False)]
    assert [record.position_nm for record in model.checked_records] == [875.0]

    tsv = model.to_tsv()
    assert tsv.splitlines() == ["AGA017\t875.0000 nm\t3"]
    assert "870" not in tsv
    assert not tsv.startswith("\t")
    assert "Include" not in tsv and "Quality" not in tsv

    model.set_all_included(True)
    assert len(model.checked_records) == 2
    assert changes[-1] == ("AGA017", 870.0, True)
    assert len(model.to_tsv().splitlines()) == 2

    model.set_all_included(False)
    assert model.checked_records == ()
    assert model.to_tsv() == ""


def test_copied_peaks_carry_only_sample_position_and_height() -> None:
    """The clipboard table has no header row and puts the unit on the position."""

    model = PeakTableModel()
    model.replace(_workspace_with_two_peaks().peak_table_records())

    lines = model.to_tsv().splitlines()

    assert len(lines) == 2
    assert lines[0].split("\t") == ["AGA017", "870.0000 nm", "5"]
    assert lines[1].split("\t") == ["AGA017", "875.0000 nm", "3"]
    assert all(len(line.split("\t")) == 3 for line in lines)
    assert "材料" not in lines[0]
    assert "GaAs" not in model.to_tsv()


def test_peak_table_model_sorts_numerically_and_keeps_the_order(
    qapp: object,
) -> None:
    workspace = _workspace_with_two_peaks()
    model = PeakTableModel()
    model.replace(workspace.peak_table_records())
    assert [record.position_nm for record in model.records] == [870.0, 875.0]

    model.sort(5, Qt.SortOrder.AscendingOrder)

    assert [record.height_au for record in model.records] == [3.0, 5.0]
    assert model.sort_state == (5, Qt.SortOrder.AscendingOrder)

    model.sort(5, Qt.SortOrder.DescendingOrder)

    assert [record.height_au for record in model.records] == [5.0, 3.0]

    model.sort(4, Qt.SortOrder.AscendingOrder)

    assert [record.position_nm for record in model.records] == [870.0, 875.0]

    model.sort(0, Qt.SortOrder.DescendingOrder)

    assert model.sort_state == (4, Qt.SortOrder.AscendingOrder)

    model.replace(workspace.peak_table_records())

    assert [record.position_nm for record in model.records] == [870.0, 875.0]


def test_peak_panel_header_clicks_toggle_ascending_and_descending(
    qtbot: pytest.FixtureRequest,
    qapp: object,
) -> None:
    materials = MaterialDatabase.from_json(application_root() / "config" / "materials.json")
    panel = PeakPanel(materials)
    qtbot.addWidget(panel)
    panel.set_records(_workspace_with_two_peaks().peak_table_records())

    panel._sort_peak_table(4)

    assert [record.position_nm for record in panel._peak_model.records] == [870.0, 875.0]
    header = panel._peak_table.horizontalHeader()
    assert header.sortIndicatorSection() == 4
    assert header.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder

    panel._sort_peak_table(5)

    assert [record.height_au for record in panel._peak_model.records] == [3.0, 5.0]
    assert header.sortIndicatorSection() == 5

    panel._sort_peak_table(5)

    assert [record.height_au for record in panel._peak_model.records] == [5.0, 3.0]
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder

    panel._sort_peak_table(0)

    assert header.sortIndicatorSection() == 5


def test_sample_panel_export_button_requests_a_workbook(qtbot: pytest.FixtureRequest) -> None:
    panel = SamplePanel()
    qtbot.addWidget(panel)
    requests: list[bool] = []
    panel.export_requested.connect(lambda: requests.append(True))

    panel._export_button.click()

    assert requests == [True]


def _build_main_window(workspace: Workspace) -> MainWindow:
    root = application_root()
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")
    return MainWindow(
        workspace=workspace,
        importer=SpectrumImportService(),
        analyzer=RawPeakAnalyzer(),
        exporter=PeakTableExporter(),
        material_database=materials,
        analysis_defaults=settings.analysis,
    )


def test_main_window_ignores_peaks_and_restores_the_decision_from_the_project(
    qtbot: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    wavelength_nm = np.linspace(600.0, 910.0, 1200)
    intensity_au = 5.0 + 0.003 * (wavelength_nm - 750.0)
    intensity_au += 40.0 * np.exp(-4.0 * np.log(2.0) * ((wavelength_nm - 645.0) / 12.0) ** 2)
    intensity_au += 70.0 * np.exp(-4.0 * np.log(2.0) * ((wavelength_nm - 875.0) / 16.0) ** 2)
    workspace = Workspace(PlotDisplaySettings())
    workspace.add_spectra(
        [
            SpectrumSeries(
                spectrum_id="pl-300k",
                name="AGA017",
                wavelength_nm=wavelength_nm,
                intensity_au=intensity_au,
                source=SourceInfo(
                    file_path="C:/PL DATA.opju",
                    sheet_name="PL 300 K",
                    wavelength_column="Wavelength",
                    intensity_column="Signal",
                ),
            )
        ]
    )
    window = _build_main_window(workspace)
    qtbot.addWidget(window)
    window._run_peak_search(show_summary=False)

    records = window._workspace.peak_table_records()
    assert len(records) >= 2
    target = records[0]
    model = window._peak_panel._peak_model
    row = next(
        position
        for position, record in enumerate(model.records)
        if record.spectrum_id == target.spectrum_id
        and record.position_nm == pytest.approx(target.position_nm)
    )
    assert model.setData(
        model.index(row, 0),
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )

    assert window._workspace.peak_included(target.spectrum_id, target.position_nm) is False
    assert all(
        peak.position_nm != pytest.approx(target.position_nm)
        for peak in window._workspace.peak_results[target.spectrum_id].peaks
    )
    assert target.position_nm not in [
        record.position_nm for record in window._checked_peak_records()
    ]

    project_path = tmp_path / "peak-selection.plproj"
    assert window._save_project_to(project_path)

    reopened = _build_main_window(Workspace(PlotDisplaySettings()))
    qtbot.addWidget(reopened)
    reopened._apply_loaded_project(reopened._project_persistence.load(project_path), project_path)

    assert reopened._workspace.peak_included(target.spectrum_id, target.position_nm) is False
    stored = reopened._workspace.ignored_peaks
    assert len(stored) == 1
    assert stored[0][0] == target.spectrum_id
    assert stored[0][1] == pytest.approx(target.position_nm, abs=1e-6)
    assert target.position_nm not in [
        record.position_nm for record in reopened._workspace.peak_table_records() if record.included
    ]
    reopened._set_dirty(False)
    window._set_dirty(False)


def test_main_window_reports_invalid_stored_peak_entries(
    qtbot: pytest.FixtureRequest,
) -> None:
    window = _build_main_window(Workspace(PlotDisplaySettings()))
    qtbot.addWidget(window)

    window._restore_ignored_peaks(
        [
            {"spectrum_id": "missing", "position_nm": 870.0},
            {"spectrum_id": "AGA017", "position_nm": "not-a-number"},
            "not-an-entry",
        ]
    )

    assert window._workspace.ignored_peaks == ()
    window._set_dirty(False)
