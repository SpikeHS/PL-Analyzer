"""Workspace identity and peak export tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.models import (
    PeakAnalysisResult,
    PeakResult,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.workspace import Workspace
from export.peak_table import PeakTableExporter


def _spectrum(identifier: str, name: str) -> SpectrumSeries:
    return SpectrumSeries(
        spectrum_id=identifier,
        name=name,
        wavelength_nm=np.asarray([860.0, 870.0, 880.0]),
        intensity_au=np.asarray([1.0, 5.0, 1.0]),
        source=SourceInfo(
            file_path=f"C:/{name}.csv",
            sheet_name=None,
            wavelength_column="Wavelength",
            intensity_column="Intensity",
        ),
    )


def test_workspace_assigns_unique_names_and_colors() -> None:
    workspace = Workspace(PlotDisplaySettings())

    added = workspace.add_spectra([_spectrum("one", "AGA017"), _spectrum("two", "AGA017")])

    assert [spectrum.name for spectrum in added] == ["AGA017", "AGA017 [2]"]
    assert added[0].display.color
    assert added[0].display.color != added[1].display.color


def test_excel_peak_export_round_trip(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    workspace = Workspace(PlotDisplaySettings())
    spectrum = _spectrum("one", "AGA017")
    workspace.add_spectra([spectrum])
    workspace.set_peak_results(
        {
            "one": PeakAnalysisResult(
                peaks=(
                    PeakResult(
                        position_nm=870.0,
                        height_au=5.0,
                        fwhm_nm=8.0,
                        prominence_au=4.0,
                        width_level_au=3.0,
                    ),
                ),
                effective_prominence_au=0.1,
                diagnostics=(),
            )
        }
    )
    target = tmp_path / "peaks.xlsx"

    PeakTableExporter().export(workspace.peak_table_records(), target)

    workbook = openpyxl.load_workbook(target, data_only=True)
    worksheet = workbook["Raw Peaks"]
    assert worksheet["A2"].value == "AGA017"
    assert worksheet["B2"].value == "Custom"
    assert worksheet["D2"].value == 870.0
    assert worksheet["F2"].value == 8.0
    workbook.close()
