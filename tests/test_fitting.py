"""Scientific and failure-contract tests for the v1.1 fitting engine."""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import pytest

from analysis.fitting import (
    BaselineMode,
    FitConfig,
    FitModel,
    SpectrumFitter,
    gaussian_peak,
    lorentzian_peak,
    pseudo_voigt_peak,
    voigt_peak,
)
from core.errors import AnalysisError


@pytest.fixture
def wavelength() -> np.ndarray:
    """Return a representative, well-sampled PL wavelength window."""

    return np.linspace(850.0, 910.0, 601)


@pytest.mark.parametrize(
    ("model", "profile", "expected_fwhm", "expected_area"),
    [
        (
            FitModel.GAUSSIAN,
            lambda x: gaussian_peak(x, 120.0, 882.0, 6.0),
            6.0,
            120.0 * 6.0 * math.sqrt(math.pi) / (2.0 * math.sqrt(math.log(2.0))),
        ),
        (
            FitModel.LORENTZIAN,
            lambda x: lorentzian_peak(x, 120.0, 882.0, 6.0),
            6.0,
            120.0 * 6.0 * math.pi / 2.0,
        ),
        (
            FitModel.PSEUDO_VOIGT,
            lambda x: pseudo_voigt_peak(x, 120.0, 882.0, 6.0, 0.35),
            6.0,
            120.0
            * 6.0
            * (0.65 * math.sqrt(math.pi) / (2.0 * math.sqrt(math.log(2.0))) + 0.35 * math.pi / 2.0),
        ),
        (
            FitModel.VOIGT,
            lambda x: voigt_peak(x, 120.0, 882.0, 4.0, 2.0),
            0.5346 * 2.0 + math.sqrt(0.2166 * 2.0**2 + 4.0**2),
            None,
        ),
    ],
)
def test_single_peak_models_recover_physical_metrics(
    wavelength: np.ndarray,
    model: FitModel,
    profile: Callable[[np.ndarray], np.ndarray],
    expected_fwhm: float,
    expected_area: float | None,
) -> None:
    intensity = profile(wavelength)
    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=model,
            peak_count=1,
            baseline=BaselineMode.NONE,
        ),
    )

    assert result.model is model
    assert result.r_squared > 0.999999
    assert len(result.peaks) == 1
    peak = result.peaks[0]
    assert peak.position_nm == pytest.approx(882.0, abs=0.01)
    assert peak.height_au == pytest.approx(120.0, rel=2e-3)
    assert peak.fwhm_nm == pytest.approx(expected_fwhm, rel=0.02)
    if expected_area is not None:
        assert peak.area_au_nm == pytest.approx(expected_area, rel=3e-3)
    else:
        assert peak.gaussian_fwhm_nm == pytest.approx(4.0, rel=0.02)
        assert peak.lorentzian_fwhm_nm == pytest.approx(2.0, rel=0.03)
        assert peak.area_au_nm > 0


def test_automatic_model_selection_prefers_gaussian(
    wavelength: np.ndarray,
) -> None:
    intensity = 3.0 + gaussian_peak(wavelength, 80.0, 878.0, 4.5)

    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.AUTO,
            peak_count=1,
            baseline=BaselineMode.CONSTANT,
        ),
    )

    assert result.model is FitModel.GAUSSIAN
    assert result.r_squared > 0.999999
    assert "AUTO_MODEL_SELECTED:gaussian" in result.diagnostics


def test_two_peaks_are_fitted_and_sorted(wavelength: np.ndarray) -> None:
    intensity = (
        2.5
        + gaussian_peak(wavelength, 75.0, 872.0, 3.5)
        + gaussian_peak(wavelength, 45.0, 891.0, 5.0)
    )

    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count=2,
            baseline=BaselineMode.CONSTANT,
        ),
    )

    assert result.r_squared > 0.999999
    assert [peak.position_nm for peak in result.peaks] == pytest.approx(
        [872.0, 891.0],
        abs=0.02,
    )
    assert [peak.height_au for peak in result.peaks] == pytest.approx(
        [75.0, 45.0],
        rel=2e-3,
    )


def test_automatic_peak_count_finds_two_resolved_peaks(
    wavelength: np.ndarray,
) -> None:
    intensity = (
        4.0
        + gaussian_peak(wavelength, 95.0, 870.0, 3.0)
        + gaussian_peak(wavelength, 70.0, 892.0, 4.0)
    )

    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count="auto",
            max_peaks=3,
            baseline=BaselineMode.CONSTANT,
        ),
    )

    assert len(result.peaks) == 2
    assert "AUTO_PEAK_COUNT_SELECTED:2" in result.diagnostics


def test_savgol_does_not_bias_auto_bic_toward_extra_peaks() -> None:
    wavelength = np.linspace(850.0, 910.0, 301)
    generator = np.random.default_rng(0)
    intensity = (
        2.0
        + gaussian_peak(wavelength, 50.0, 880.0, 5.0)
        + generator.normal(0.0, 1.0, wavelength.size)
    )
    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count="auto",
            max_peaks=3,
            baseline=BaselineMode.CONSTANT,
            savgol_enabled=True,
            savgol_window_length=21,
            savgol_polyorder=3,
        ),
    )

    assert len(result.peaks) == 1
    np.testing.assert_allclose(
        result.residuals_au,
        result.observed_intensity_au - result.fitted_intensity_au,
    )
    total_sum_squares = float(
        np.sum((result.observed_intensity_au - np.mean(result.observed_intensity_au)) ** 2)
    )
    expected_r_squared = 1.0 - float(np.sum(result.residuals_au**2)) / total_sum_squares
    assert result.r_squared == pytest.approx(expected_r_squared)
    assert "SAVGOL_INITIALIZATION_ONLY" in result.diagnostics


@pytest.mark.parametrize(
    ("baseline", "expected_intercept", "expected_slope"),
    [
        (BaselineMode.CONSTANT, 7.5, 0.0),
        (BaselineMode.LINEAR, 6.0, 0.08),
    ],
)
def test_baseline_is_jointly_recovered(
    wavelength: np.ndarray,
    baseline: BaselineMode,
    expected_intercept: float,
    expected_slope: float,
) -> None:
    reference = float(np.mean(wavelength))
    baseline_values = expected_intercept + expected_slope * (wavelength - reference)
    intensity = baseline_values + gaussian_peak(wavelength, 50.0, 883.0, 5.5)

    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count=1,
            baseline=baseline,
        ),
    )

    assert result.baseline.mode is baseline
    assert result.baseline.intercept_au == pytest.approx(expected_intercept, abs=1e-3)
    assert result.baseline.slope_au_per_nm == pytest.approx(
        expected_slope,
        abs=1e-4,
    )
    assert result.r_squared > 0.999999


def test_savgol_preprocessing_is_non_destructive(
    wavelength: np.ndarray,
) -> None:
    generator = np.random.default_rng(20260723)
    original = (
        5.0
        + gaussian_peak(wavelength, 60.0, 884.0, 5.0)
        + generator.normal(0.0, 0.7, wavelength.size)
    )
    source_copy = original.copy()
    wavelength_copy = wavelength.copy()

    result = SpectrumFitter().fit(
        wavelength,
        original,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count=1,
            baseline=BaselineMode.CONSTANT,
            savgol_enabled=True,
            savgol_window_length=15,
            savgol_polyorder=3,
        ),
    )

    np.testing.assert_array_equal(original, source_copy)
    np.testing.assert_array_equal(wavelength, wavelength_copy)
    np.testing.assert_array_equal(result.observed_intensity_au, source_copy)
    assert not np.array_equal(result.processed_intensity_au, source_copy)
    assert "SAVGOL_APPLIED" in result.diagnostics
    assert result.peaks[0].position_nm == pytest.approx(884.0, abs=0.15)
    assert not result.wavelength_nm.flags.writeable
    assert not result.fitted_intensity_au.flags.writeable


def test_savgol_rejects_a_nonuniform_wavelength_axis() -> None:
    uniform_parameter = np.linspace(0.0, 1.0, 301)
    wavelength = 850.0 + 60.0 * uniform_parameter**2
    intensity = 4.0 + gaussian_peak(wavelength, 70.0, 880.0, 4.0)

    with pytest.raises(AnalysisError) as captured:
        SpectrumFitter().fit(
            wavelength,
            intensity,
            FitConfig(
                model=FitModel.GAUSSIAN,
                peak_count=1,
                baseline=BaselineMode.CONSTANT,
                savgol_enabled=True,
                savgol_window_length=15,
                savgol_polyorder=3,
            ),
        )

    assert captured.value.code == "E_FIT_SAVGOL_NONUNIFORM_AXIS"

    unsmoothed = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count=1,
            baseline=BaselineMode.CONSTANT,
        ),
    )
    assert unsmoothed.peaks[0].position_nm == pytest.approx(880.0, abs=0.01)


@pytest.mark.parametrize(
    "model",
    (
        FitModel.GAUSSIAN,
        FitModel.LORENTZIAN,
        FitModel.PSEUDO_VOIGT,
        FitModel.VOIGT,
    ),
)
def test_under_sampled_fwhm_is_rejected(model: FitModel) -> None:
    wavelength = np.linspace(0.0, 10.0, 101)
    intensity = gaussian_peak(wavelength, 10.0, 5.0, 0.02)

    with pytest.raises(AnalysisError) as captured:
        SpectrumFitter().fit(
            wavelength,
            intensity,
            FitConfig(
                model=model,
                peak_count=1,
                baseline=BaselineMode.NONE,
            ),
        )

    assert captured.value.code == "E_FIT_UNRESOLVED_PEAK"


def test_coincident_fitted_peaks_are_rejected(wavelength: np.ndarray) -> None:
    intensity = gaussian_peak(wavelength, 100.0, 880.0, 5.0)

    with pytest.raises(AnalysisError) as captured:
        SpectrumFitter().fit(
            wavelength,
            intensity,
            FitConfig(
                model=FitModel.GAUSSIAN,
                peak_count=2,
                baseline=BaselineMode.NONE,
            ),
        )

    assert captured.value.code == "E_FIT_UNRESOLVED_PEAK"


def test_adjusted_r_squared_uses_residual_degrees_of_freedom() -> None:
    generator = np.random.default_rng(7)
    wavelength = np.linspace(0.0, 10.0, 20)
    intensity = (
        2.0
        + gaussian_peak(wavelength, 10.0, 5.0, 2.0)
        + generator.normal(0.0, 0.5, wavelength.size)
    )
    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            model=FitModel.GAUSSIAN,
            peak_count=1,
            baseline=BaselineMode.CONSTANT,
        ),
    )
    fitted_parameter_count = 4
    expected = 1.0 - (
        (1.0 - result.r_squared)
        * (wavelength.size - 1)
        / (wavelength.size - fitted_parameter_count)
    )

    assert result.adjusted_r_squared == pytest.approx(expected)


def test_fit_window_is_applied_and_preserved(wavelength: np.ndarray) -> None:
    intensity = gaussian_peak(wavelength, 40.0, 880.0, 4.0)

    result = SpectrumFitter().fit(
        wavelength,
        intensity,
        FitConfig(
            search_min_nm=870.03,
            search_max_nm=890.07,
            model=FitModel.GAUSSIAN,
            peak_count=1,
            baseline=BaselineMode.NONE,
        ),
    )

    assert result.window_min_nm == pytest.approx(870.1)
    assert result.window_max_nm == pytest.approx(890.0)
    assert result.wavelength_nm[0] == result.window_min_nm
    assert result.wavelength_nm[-1] == result.window_max_nm


@pytest.mark.parametrize(
    ("wavelength", "intensity", "config", "error_code"),
    [
        (
            [[1.0, 2.0], [3.0, 4.0]],
            [[1.0, 2.0], [3.0, 4.0]],
            FitConfig(),
            "E_FIT_SHAPE",
        ),
        (
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [1.0, 2.0],
            FitConfig(),
            "E_FIT_LENGTH_MISMATCH",
        ),
        (
            [1.0, 2.0, 3.0, 4.0],
            [1.0, 2.0, 1.0, 0.0],
            FitConfig(),
            "E_FIT_INSUFFICIENT_POINTS",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            np.full(20, np.nan),
            FitConfig(),
            "E_FIT_NO_FINITE_DATA",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            np.ones(20),
            FitConfig(model=FitModel.GAUSSIAN, peak_count=1),
            "E_FIT_NO_PEAK_SIGNAL",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(search_min_nm=7.0, search_max_nm=3.0),
            "E_FIT_INVALID_WINDOW",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(search_min_nm=20.0, search_max_nm=30.0),
            "E_FIT_NO_DATA_IN_WINDOW",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(savgol_enabled=True, savgol_window_length=4),
            "E_FIT_INVALID_SAVGOL",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(model="unsupported"),
            "E_FIT_INVALID_MODEL",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(search_min_nm="not-a-number"),
            "E_FIT_INVALID_WINDOW",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(search_max_nm=[]),
            "E_FIT_INVALID_WINDOW",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(min_peak_distance_nm="not-a-number"),
            "E_FIT_INVALID_CONFIG",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(min_peak_distance_nm=None),
            "E_FIT_INVALID_CONFIG",
        ),
        (
            np.linspace(1.0, 10.0, 20),
            gaussian_peak(np.linspace(1.0, 10.0, 20), 1.0, 5.0, 1.0),
            FitConfig(savgol_enabled="yes"),
            "E_FIT_INVALID_CONFIG",
        ),
    ],
)
def test_failures_have_stable_error_codes(
    wavelength: object,
    intensity: object,
    config: FitConfig,
    error_code: str,
) -> None:
    with pytest.raises(AnalysisError) as captured:
        SpectrumFitter().fit(wavelength, intensity, config)

    assert captured.value.code == error_code
