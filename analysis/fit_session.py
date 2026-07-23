"""Material-labelled fit result storage, tables, and project serialization."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from analysis.fitting import (
    BaselineMode,
    FitBaseline,
    FitModel,
    FitPeak,
    FitResult,
)
from core.errors import AnalysisError
from core.models import MaterialSearchWindow
from core.project import JSONValue


@dataclass(frozen=True, slots=True)
class MaterialFitAnalysis:
    """One fitted spectrum within one material-labelled window."""

    spectrum_id: str
    sample_name: str
    window: MaterialSearchWindow
    result: FitResult


@dataclass(frozen=True, slots=True)
class FitTableRecord:
    """One fitted peak flattened with shared fit-quality metrics."""

    sample_name: str
    material_name: str
    model: FitModel
    peak_number: int
    position_nm: float
    height_au: float
    area_au_nm: float
    fwhm_nm: float
    gaussian_fwhm_nm: float | None
    lorentzian_fwhm_nm: float | None
    mixing_fraction: float | None
    r_squared: float
    adjusted_r_squared: float | None
    aic: float
    bic: float
    baseline_mode: BaselineMode


class FitResultStore:
    """Own the current successful v1.1 fit snapshot."""

    schema_version = 1

    def __init__(
        self,
        assignments: tuple[MaterialFitAnalysis, ...] = (),
    ) -> None:
        self._assignments = tuple(assignments)

    @property
    def assignments(self) -> tuple[MaterialFitAnalysis, ...]:
        """Return all fits in sample/material order."""

        return self._assignments

    def replace(self, assignments: tuple[MaterialFitAnalysis, ...]) -> None:
        """Replace all fit results after one operator fit request."""

        self._assignments = tuple(assignments)

    def clear(self) -> None:
        """Remove all fitted results."""

        self._assignments = ()

    def remove_spectra(self, spectrum_ids: set[str]) -> None:
        """Discard fits derived from removed spectra."""

        self._assignments = tuple(
            assignment
            for assignment in self._assignments
            if assignment.spectrum_id not in spectrum_ids
        )

    def table_records(self) -> tuple[FitTableRecord, ...]:
        """Flatten fitted peaks for UI and export."""

        records: list[FitTableRecord] = []
        for assignment in self._assignments:
            for peak_number, peak in enumerate(assignment.result.peaks, start=1):
                records.append(
                    FitTableRecord(
                        sample_name=assignment.sample_name,
                        material_name=assignment.window.material_name,
                        model=assignment.result.model,
                        peak_number=peak_number,
                        position_nm=peak.position_nm,
                        height_au=peak.height_au,
                        area_au_nm=peak.area_au_nm,
                        fwhm_nm=peak.fwhm_nm,
                        gaussian_fwhm_nm=peak.gaussian_fwhm_nm,
                        lorentzian_fwhm_nm=peak.lorentzian_fwhm_nm,
                        mixing_fraction=peak.mixing_fraction,
                        r_squared=assignment.result.r_squared,
                        adjusted_r_squared=assignment.result.adjusted_r_squared,
                        aic=assignment.result.aic,
                        bic=assignment.result.bic,
                        baseline_mode=assignment.result.baseline.mode,
                    )
                )
        return tuple(records)

    def to_project_payload(self) -> dict[str, JSONValue]:
        """Serialize complete fits for lossless ``.plproj`` recovery."""

        return {
            "schema_version": self.schema_version,
            "assignments": [_assignment_to_payload(assignment) for assignment in self._assignments],
        }

    @classmethod
    def from_project_payload(cls, payload: object) -> FitResultStore:
        """Decode and validate a fit store from project JSON."""

        if not isinstance(payload, dict):
            raise AnalysisError(
                "Fit project data must be an object.",
                code="E_FIT_PROJECT_FORMAT",
            )
        if not payload:
            return cls()
        if payload.get("schema_version") != cls.schema_version:
            raise AnalysisError(
                "Unsupported fit-result project schema.",
                code="E_FIT_PROJECT_VERSION",
            )
        encoded_assignments = payload.get("assignments")
        if not isinstance(encoded_assignments, list):
            raise AnalysisError(
                "Fit project assignments must be an array.",
                code="E_FIT_PROJECT_FORMAT",
            )
        try:
            assignments = tuple(
                _assignment_from_payload(_object(item, "fit assignment"))
                for item in encoded_assignments
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisError(
                "Fit project data is invalid.",
                code="E_FIT_PROJECT_FORMAT",
                detail=str(exc),
            ) from exc
        return cls(assignments)


def _assignment_to_payload(assignment: MaterialFitAnalysis) -> dict[str, JSONValue]:
    result = assignment.result
    return {
        "spectrum_id": assignment.spectrum_id,
        "sample_name": assignment.sample_name,
        "window": {
            "material_id": assignment.window.material_id,
            "material_name": assignment.window.material_name,
            "min_nm": assignment.window.min_nm,
            "max_nm": assignment.window.max_nm,
        },
        "result": {
            "algorithm_version": result.algorithm_version,
            "model": result.model.value,
            "peaks": [
                {
                    "model": peak.model.value,
                    "position_nm": peak.position_nm,
                    "height_au": peak.height_au,
                    "area_au_nm": peak.area_au_nm,
                    "fwhm_nm": peak.fwhm_nm,
                    "gaussian_fwhm_nm": peak.gaussian_fwhm_nm,
                    "lorentzian_fwhm_nm": peak.lorentzian_fwhm_nm,
                    "mixing_fraction": peak.mixing_fraction,
                }
                for peak in result.peaks
            ],
            "baseline": {
                "mode": result.baseline.mode.value,
                "intercept_au": result.baseline.intercept_au,
                "slope_au_per_nm": result.baseline.slope_au_per_nm,
                "reference_nm": result.baseline.reference_nm,
            },
            "wavelength_nm": result.wavelength_nm.tolist(),
            "observed_intensity_au": result.observed_intensity_au.tolist(),
            "processed_intensity_au": result.processed_intensity_au.tolist(),
            "fitted_intensity_au": result.fitted_intensity_au.tolist(),
            "baseline_intensity_au": result.baseline_intensity_au.tolist(),
            "residuals_au": result.residuals_au.tolist(),
            "r_squared": result.r_squared,
            "adjusted_r_squared": result.adjusted_r_squared,
            "aic": result.aic,
            "bic": result.bic,
            "window_min_nm": result.window_min_nm,
            "window_max_nm": result.window_max_nm,
            "diagnostics": list(result.diagnostics),
        },
    }


def _assignment_from_payload(payload: dict[str, Any]) -> MaterialFitAnalysis:
    window = _object(payload["window"], "fit window")
    result_payload = _object(payload["result"], "fit result")
    baseline_payload = _object(result_payload["baseline"], "fit baseline")
    peaks_payload = _array(result_payload["peaks"], "fit peaks")
    result = FitResult(
        model=FitModel(_text(result_payload["model"], "fit model")),
        peaks=tuple(_fit_peak_from_payload(_object(peak, "fit peak")) for peak in peaks_payload),
        baseline=FitBaseline(
            mode=BaselineMode(_text(baseline_payload["mode"], "baseline mode")),
            intercept_au=_finite(baseline_payload["intercept_au"], "intercept_au"),
            slope_au_per_nm=_finite(
                baseline_payload["slope_au_per_nm"],
                "slope_au_per_nm",
            ),
            reference_nm=_finite(baseline_payload["reference_nm"], "reference_nm"),
        ),
        wavelength_nm=_float_array(result_payload["wavelength_nm"], "wavelength_nm"),
        observed_intensity_au=_float_array(
            result_payload["observed_intensity_au"],
            "observed_intensity_au",
        ),
        processed_intensity_au=_float_array(
            result_payload["processed_intensity_au"],
            "processed_intensity_au",
        ),
        fitted_intensity_au=_float_array(
            result_payload["fitted_intensity_au"],
            "fitted_intensity_au",
        ),
        baseline_intensity_au=_float_array(
            result_payload["baseline_intensity_au"],
            "baseline_intensity_au",
        ),
        residuals_au=_float_array(result_payload["residuals_au"], "residuals_au"),
        r_squared=_finite(result_payload["r_squared"], "r_squared"),
        adjusted_r_squared=_optional_finite(
            result_payload.get("adjusted_r_squared"),
            "adjusted_r_squared",
        ),
        aic=_finite(result_payload["aic"], "aic"),
        bic=_finite(result_payload["bic"], "bic"),
        window_min_nm=_finite(result_payload["window_min_nm"], "window_min_nm"),
        window_max_nm=_finite(result_payload["window_max_nm"], "window_max_nm"),
        diagnostics=tuple(
            _text(item, "fit diagnostic")
            for item in _array(result_payload.get("diagnostics", []), "diagnostics")
        ),
        algorithm_version=_integer(
            result_payload.get("algorithm_version", 1),
            "algorithm_version",
        ),
    )
    return MaterialFitAnalysis(
        spectrum_id=_text(payload["spectrum_id"], "spectrum_id"),
        sample_name=_text(payload["sample_name"], "sample_name"),
        window=MaterialSearchWindow(
            material_id=_text(window["material_id"], "material_id"),
            material_name=_text(window["material_name"], "material_name"),
            min_nm=_finite(window["min_nm"], "min_nm"),
            max_nm=_finite(window["max_nm"], "max_nm"),
        ),
        result=result,
    )


def _fit_peak_from_payload(payload: dict[str, Any]) -> FitPeak:
    return FitPeak(
        model=FitModel(_text(payload["model"], "peak model")),
        position_nm=_finite(payload["position_nm"], "position_nm"),
        height_au=_finite(payload["height_au"], "height_au"),
        area_au_nm=_finite(payload["area_au_nm"], "area_au_nm"),
        fwhm_nm=_finite(payload["fwhm_nm"], "fwhm_nm"),
        gaussian_fwhm_nm=_optional_finite(
            payload.get("gaussian_fwhm_nm"),
            "gaussian_fwhm_nm",
        ),
        lorentzian_fwhm_nm=_optional_finite(
            payload.get("lorentzian_fwhm_nm"),
            "lorentzian_fwhm_nm",
        ),
        mixing_fraction=_optional_finite(
            payload.get("mixing_fraction"),
            "mixing_fraction",
        ),
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be an object.")
    return value


def _array(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array.")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text.")
    return value


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be finite.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number


def _optional_finite(value: object, name: str) -> float | None:
    return None if value is None else _finite(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _float_array(value: object, name: str) -> np.ndarray:
    return np.asarray([_finite(item, name) for item in _array(value, name)])
