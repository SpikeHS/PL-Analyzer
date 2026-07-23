"""Scientific edge cases for direct raw peak measurement."""

from __future__ import annotations

import numpy as np
import pytest

from analysis.raw_peak import RawPeakAnalyzer, RawPeakConfig
from core.errors import AnalysisError


def _config(minimum: float = 0, maximum: float = 10, **kwargs: float) -> RawPeakConfig:
    return RawPeakConfig(
        search_min_nm=minimum,
        search_max_nm=maximum,
        min_prominence_au=kwargs.pop("min_prominence_au", 0.1),
        min_distance_nm=kwargs.pop("min_distance_nm", 0.0),
        **kwargs,
    )


def test_exact_sampled_peak_and_fwhm() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 2, 3, 4],
        [0, 1, 4, 1, 0],
        _config(),
    )

    assert len(result.peaks) == 1
    peak = result.peaks[0]
    assert peak.position_nm == 2
    assert peak.height_au == 4
    assert peak.fwhm_nm == pytest.approx(4 / 3)


def test_fwhm_is_interpolated_on_irregular_wavelength_axis() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 0.2, 1, 4, 10],
        [0, 1, 4, 2, 0],
        _config(),
    )

    assert result.peaks[0].fwhm_nm == pytest.approx(3.5333333333)


def test_plateau_is_flagged_without_fitting() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 2, 3, 4],
        [0, 4, 4, 4, 0],
        _config(),
    )

    peak = result.peaks[0]
    assert peak.position_nm == 2
    assert peak.fwhm_nm == pytest.approx(3.0)
    assert "PLATEAU" in peak.quality_flags


def test_duplicate_wavelengths_are_averaged() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 1, 2, 3, 4],
        [0, 2, 4, 6, 2, 0],
        _config(),
    )

    assert result.peaks[0].height_au == 6
    assert result.peaks[0].fwhm_nm == pytest.approx(1.75)
    assert "DUPLICATE_WAVELENGTH_AVERAGED" in result.diagnostics


def test_missing_intensity_splits_width_measurement() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 2, 3, 4],
        [0, 4, np.nan, 4, 0],
        _config(),
    )

    assert len(result.peaks) == 2
    assert all(peak.fwhm_nm is None for peak in result.peaks)
    assert {peak.quality_flags[0] for peak in result.peaks} == {
        "TRUNCATED_LEFT",
        "TRUNCATED_RIGHT",
    }
    assert "NONFINITE_INTENSITY_SEGMENTED" in result.diagnostics


def test_boundary_peak_is_reported_but_width_is_unresolved() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 2, 3],
        [5, 4, 2, 0],
        _config(),
    )

    assert result.peaks[0].position_nm == 0
    assert result.peaks[0].fwhm_nm is None
    assert result.peaks[0].quality_flags == ("TRUNCATED_LEFT",)


def test_constant_spectrum_has_no_peak() -> None:
    result = RawPeakAnalyzer().analyze(
        [0, 1, 2, 3],
        [2, 2, 2, 2],
        _config(),
    )

    assert result.peaks == ()


def test_reverse_wavelength_order_is_equivalent() -> None:
    analyzer = RawPeakAnalyzer()
    forward = analyzer.analyze([0, 1, 2, 3, 4], [0, 1, 4, 1, 0], _config())
    reverse = analyzer.analyze([4, 3, 2, 1, 0], [0, 1, 4, 1, 0], _config())

    assert reverse.peaks == forward.peaks
    assert "WAVELENGTH_SORTED" in reverse.diagnostics


def test_minimum_distance_uses_nanometres() -> None:
    result = RawPeakAnalyzer().analyze(
        np.arange(0, 11, dtype=float),
        [0, 1, 5, 1, 0, 0, 1, 4, 1, 0, 0],
        _config(min_distance_nm=6.0),
    )

    assert len(result.peaks) == 1
    assert result.peaks[0].position_nm == 2


@pytest.mark.parametrize(
    ("wavelength", "intensity", "config", "error_code"),
    [
        ([1, 2], [1, 2], _config(), "E_PEAK_INSUFFICIENT_POINTS"),
        ([1, 2, 3], [1, 2], _config(), "E_PEAK_LENGTH_MISMATCH"),
        ([1, 2, 3], [np.nan, np.nan, np.nan], _config(), "E_PEAK_NO_FINITE_DATA"),
        (
            [1, 2, 3],
            [1, 2, 1],
            RawPeakConfig(search_min_nm=3, search_max_nm=2),
            "E_PEAK_INVALID_WINDOW",
        ),
    ],
)
def test_invalid_inputs_have_stable_error_codes(
    wavelength: list[float],
    intensity: list[float],
    config: RawPeakConfig,
    error_code: str,
) -> None:
    with pytest.raises(AnalysisError) as captured:
        RawPeakAnalyzer().analyze(wavelength, intensity, config)

    assert captured.value.code == error_code
