"""Fit-result storage, project payload, and table export tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from analysis.fit_session import FitResultStore, MaterialFitAnalysis
from analysis.fitting import (
    BaselineMode,
    FitBaseline,
    FitModel,
    FitPeak,
    FitResult,
)
from core.models import (
    MaterialSearchWindow,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.persistence import ProjectPersistence
from core.project import MaterialWindowSnapshot, PLProject
from core.workspace import Workspace
from export.fit_table import FitTableExporter


def _fit_assignment() -> MaterialFitAnalysis:
    wavelength_nm = np.asarray([620.0, 630.0, 640.0, 650.0, 660.0])
    observed = np.asarray([3.0, 8.0, 30.0, 9.0, 4.0])
    processed = np.asarray([3.1, 8.1, 29.8, 9.2, 3.9])
    fitted = np.asarray([3.0, 7.9, 29.9, 9.1, 4.0])
    baseline = np.asarray([2.8, 2.9, 3.0, 3.1, 3.2])
    residuals = observed - fitted
    return MaterialFitAnalysis(
        spectrum_id="AGA017::PL",
        sample_name="AGA017 / PL",
        window=MaterialSearchWindow(
            material_id="algaas_al040_300k",
            material_name="AlGaAs x=0.40 (300 K)",
            min_nm=620.0,
            max_nm=670.0,
        ),
        result=FitResult(
            model=FitModel.VOIGT,
            peaks=(
                FitPeak(
                    model=FitModel.VOIGT,
                    position_nm=644.75,
                    height_au=27.25,
                    area_au_nm=180.5,
                    fwhm_nm=7.4,
                    gaussian_fwhm_nm=5.2,
                    lorentzian_fwhm_nm=2.1,
                    mixing_fraction=None,
                ),
            ),
            baseline=FitBaseline(
                mode=BaselineMode.LINEAR,
                intercept_au=3.0,
                slope_au_per_nm=0.01,
                reference_nm=640.0,
            ),
            wavelength_nm=wavelength_nm,
            observed_intensity_au=observed,
            processed_intensity_au=processed,
            fitted_intensity_au=fitted,
            baseline_intensity_au=baseline,
            residuals_au=residuals,
            r_squared=0.9987,
            adjusted_r_squared=0.9979,
            aic=-22.5,
            bic=-19.75,
            window_min_nm=620.0,
            window_max_nm=660.0,
            diagnostics=("SAVGOL_APPLIED", "AUTO_MODEL_SELECTED:voigt"),
            algorithm_version=2,
        ),
    )


def _fit_store() -> FitResultStore:
    return FitResultStore((_fit_assignment(),))


def _workspace() -> Workspace:
    workspace = Workspace(PlotDisplaySettings())
    workspace.add_spectra(
        [
            SpectrumSeries(
                spectrum_id="AGA017::PL",
                name="AGA017 / PL",
                wavelength_nm=np.asarray([620.0, 640.0, 660.0]),
                intensity_au=np.asarray([3.0, 30.0, 4.0]),
                source=SourceInfo(
                    file_path="C:/data/AGA017.xlsx",
                    sheet_name="PL",
                    wavelength_column="Wavelength",
                    intensity_column="Intensity",
                ),
            )
        ]
    )
    return workspace


def test_fit_result_store_payload_round_trip_is_complete() -> None:
    original = _fit_store()

    payload = original.to_project_payload()
    json.dumps(payload, allow_nan=False)
    restored = FitResultStore.from_project_payload(payload)

    assert len(restored.assignments) == 1
    assignment = restored.assignments[0]
    expected = original.assignments[0]
    assert assignment.spectrum_id == expected.spectrum_id
    assert assignment.sample_name == expected.sample_name
    assert assignment.window == expected.window
    assert assignment.result.model is FitModel.VOIGT
    assert assignment.result.peaks == expected.result.peaks
    assert assignment.result.baseline == expected.result.baseline
    assert assignment.result.r_squared == pytest.approx(0.9987)
    assert assignment.result.adjusted_r_squared == pytest.approx(0.9979)
    assert assignment.result.aic == pytest.approx(-22.5)
    assert assignment.result.bic == pytest.approx(-19.75)
    assert assignment.result.window_min_nm == pytest.approx(620.0)
    assert assignment.result.window_max_nm == pytest.approx(660.0)
    assert assignment.result.diagnostics == (
        "SAVGOL_APPLIED",
        "AUTO_MODEL_SELECTED:voigt",
    )
    assert assignment.result.algorithm_version == 2

    array_fields = (
        "wavelength_nm",
        "observed_intensity_au",
        "processed_intensity_au",
        "fitted_intensity_au",
        "baseline_intensity_au",
        "residuals_au",
    )
    for field_name in array_fields:
        restored_array = getattr(assignment.result, field_name)
        np.testing.assert_array_equal(
            restored_array,
            getattr(expected.result, field_name),
        )
        assert restored_array.flags.writeable is False


def test_fit_table_exporter_writes_csv(tmp_path: Path) -> None:
    target = tmp_path / "fit-results.csv"

    FitTableExporter().export(_fit_store().table_records(), target)

    with target.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0] == [
        "Sample",
        "Material",
        "Model",
        "Peak",
        "Position (nm)",
        "Height (a.u.)",
        "Area (a.u. nm)",
        "FWHM (nm)",
        "Gaussian FWHM (nm)",
        "Lorentzian FWHM (nm)",
        "Pseudo-Voigt Mixing Fraction",
        "R Squared",
        "Adjusted R Squared",
        "AIC",
        "BIC",
        "Baseline",
    ]
    assert rows[1][0:5] == [
        "AGA017 / PL",
        "AlGaAs x=0.40 (300 K)",
        "voigt",
        "1",
        "644.75",
    ]
    assert rows[1][8:11] == ["5.2", "2.1", ""]
    assert rows[1][11:16] == [
        "0.9987",
        "0.9979",
        "-22.5",
        "-19.75",
        "linear",
    ]


def test_fit_table_exporter_writes_xlsx(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "fit-results.xlsx"

    FitTableExporter().export(_fit_store().table_records(), target)

    workbook = openpyxl.load_workbook(target, data_only=True)
    worksheet = workbook["Model Fits"]
    assert worksheet.freeze_panes == "A2"
    assert worksheet.auto_filter.ref == "A1:P2"
    assert worksheet["A2"].value == "AGA017 / PL"
    assert worksheet["B2"].value == "AlGaAs x=0.40 (300 K)"
    assert worksheet["C2"].value == "voigt"
    assert worksheet["E2"].value == pytest.approx(644.75)
    assert worksheet["G2"].value == pytest.approx(180.5)
    assert worksheet["I2"].value == pytest.approx(5.2)
    assert worksheet["J2"].value == pytest.approx(2.1)
    assert worksheet["K2"].value is None
    assert worksheet["L2"].value == pytest.approx(0.9987)
    assert worksheet["P2"].value == "linear"
    workbook.close()


def test_plproj_round_trip_preserves_fit_store_and_selected_windows(
    tmp_path: Path,
) -> None:
    project = PLProject(
        workspace=_workspace(),
        material_windows=[
            MaterialWindowSnapshot(
                material_id="gaas_300k",
                display_name="GaAs (300 K)",
                minimum_nm=860.0,
                maximum_nm=900.0,
                selected=True,
            ),
            MaterialWindowSnapshot(
                material_id="inp_300k",
                display_name="InP (300 K)",
                minimum_nm=890.0,
                maximum_nm=970.0,
                selected=False,
            ),
            MaterialWindowSnapshot(
                material_id="custom_alloy",
                display_name="Custom alloy",
                minimum_nm=None,
                maximum_nm=None,
                selected=False,
            ),
        ],
        fit_results=_fit_store().to_project_payload(),
    )
    target = tmp_path / "fit-session.plproj"

    ProjectPersistence().save(project, target)
    restored_project = ProjectPersistence().load(target)
    restored_store = FitResultStore.from_project_payload(restored_project.fit_results)

    assert [
        (
            window.material_id,
            window.minimum_nm,
            window.maximum_nm,
            window.selected,
        )
        for window in restored_project.material_windows
    ] == [
        ("gaas_300k", 860.0, 900.0, True),
        ("inp_300k", 890.0, 970.0, False),
        ("custom_alloy", None, None, False),
    ]
    assert restored_store.assignments[0].window.material_id == "algaas_al040_300k"
    assert restored_store.assignments[0].result.peaks[0].area_au_nm == pytest.approx(180.5)
    np.testing.assert_array_equal(
        restored_store.assignments[0].result.processed_intensity_au,
        np.asarray([3.1, 8.1, 29.8, 9.2, 3.9]),
    )

    encoded = json.loads(target.read_text(encoding="utf-8"))
    saved_project = encoded["project"]
    assert [item["selected"] for item in saved_project["material_windows"]] == [
        True,
        False,
        False,
    ]
    assert (
        saved_project["analysis_results"]["fit"]["assignments"][0]["result"]["algorithm_version"]
        == 2
    )
