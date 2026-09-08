"""Display-assisted metric and reference-style PNG regression tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from analysis.presentation import PresentationAnalyzer
from core.errors import ExportError
from core.models import SourceInfo, SpectrumSeries
from export.presentation_plot import PresentationPlotExporter, PresentationPlotStyle


def _spectrum() -> SpectrumSeries:
    wavelength = np.linspace(600.0, 1000.0, 801)
    main_peak = 5.0 * np.exp(-0.5 * ((wavelength - 760.0) / 12.0) ** 2)
    shoulder = 0.30 * np.exp(-0.5 * ((wavelength - 880.0) / 10.0) ** 2)
    return SpectrumSeries(
        spectrum_id="QW-99",
        name="QW-99",
        wavelength_nm=wavelength,
        intensity_au=main_peak + shoulder + 0.01,
        source=SourceInfo(
            file_path="synthetic.dat",
            sheet_name=None,
            wavelength_column="Wavelength (nm)",
            intensity_column="Corrected signal (mV)",
            metadata=(
                ("Folder", r"d:\private\laboratory\QW-99"),
                ("Operator", "Private Name"),
                ("Laser", "532.0 nm"),
                ("Power", "45.0 mW"),
                ("Temperature", "25.0 C"),
            ),
        ),
    )


def test_presentation_analysis_keeps_fwhm_semantics_explicit() -> None:
    analysis = PresentationAnalyzer().analyze(_spectrum())

    assert analysis.metrics.peak_wavelength_nm == pytest.approx(760.0, abs=1.0)
    assert analysis.metrics.presentation_fwhm_nm == pytest.approx(28.3, abs=2.0)
    assert analysis.metrics.peak_energy_ev == pytest.approx(1.631, abs=0.01)
    assert analysis.metrics.secondary_features
    assert analysis.metrics.secondary_features[0].wavelength_nm == pytest.approx(880.0, abs=2.0)
    assert not analysis.smoothed_intensity_au.flags.writeable


def test_reference_plot_export_writes_requested_pixel_dimensions(tmp_path: Path) -> None:
    target = tmp_path / "QW-99_PL_spectrum.png"
    metrics_target = tmp_path / "QW-99_PL_metrics.json"
    data_target = tmp_path / "QW-99_PL_processed.csv"
    style = PresentationPlotStyle(width_px=1200, height_px=750, dpi=150)

    analysis = PresentationPlotExporter().export(
        _spectrum(),
        target,
        style=style,
        metrics_json_path=metrics_target,
        processed_csv_path=data_target,
    )

    assert target.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    from matplotlib.image import imread

    image = imread(target)
    assert image.shape[:2] == (750, 1200)
    assert analysis.metrics.presentation_fwhm_nm > 0
    assert '"schema_version": 1' in metrics_target.read_text(encoding="utf-8")
    assert "Presentation FWHM" in metrics_target.read_text(encoding="utf-8")
    assert "Private Name" not in metrics_target.read_text(encoding="utf-8")
    assert "private\\\\laboratory" not in metrics_target.read_text(encoding="utf-8")
    assert (
        data_target.read_text(encoding="utf-8-sig")
        .splitlines()[0]
        .startswith("Wavelength (nm),Imported intensity")
    )


def test_reference_plot_export_rejects_non_png(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as caught:
        PresentationPlotExporter().export(_spectrum(), tmp_path / "plot.pdf")

    assert caught.value.code == "E_EXPORT_FORMAT"
