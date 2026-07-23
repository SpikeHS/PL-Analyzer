"""Versioned, atomic JSON persistence for PL Analyzer Pro projects."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np

from core.errors import PLAnalyzerError
from core.models import (
    AmplitudeMode,
    AxisScale,
    DisplayStyle,
    MaterialPeakAnalysis,
    MaterialSearchWindow,
    PeakAnalysisResult,
    PeakResult,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.project import JSONValue, Layer, MaterialWindowSnapshot, PLProject
from core.workspace import Workspace

PROJECT_FORMAT_ID = "pl-analyzer-pro-project"
PROJECT_SCHEMA_VERSION = 2

type Migration = Callable[[dict[str, Any]], dict[str, Any]]


class ProjectPersistenceError(PLAnalyzerError):
    """Raised when a project cannot be safely read or written."""


class UnsupportedProjectVersionError(ProjectPersistenceError):
    """Raised when a project requires an unsupported schema version."""


def _default_migrations() -> dict[int, Migration]:
    """Return built-in, single-step project migrations."""

    return {1: _migrate_v1_to_v2}


def _migrate_v1_to_v2(payload: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize material IDs introduced by the material database v2."""

    migrated = copy.deepcopy(payload)
    project = migrated.get("project")
    if isinstance(project, dict):
        material_windows = project.get("material_windows")
        if isinstance(material_windows, list):
            for window in material_windows:
                _rewrite_legacy_material_id(window)

        analysis_results = project.get("analysis_results")
        if isinstance(analysis_results, dict):
            raw_peak = analysis_results.get("raw_peak")
            if isinstance(raw_peak, dict):
                for analyses in raw_peak.values():
                    if not isinstance(analyses, list):
                        continue
                    for analysis in analyses:
                        _rewrite_assignment_window(analysis)

            fit_results = analysis_results.get("fit")
            if isinstance(fit_results, dict):
                assignments = fit_results.get("assignments")
                if isinstance(assignments, list):
                    for assignment in assignments:
                        _rewrite_assignment_window(assignment)

    migrated["schema_version"] = 2
    return migrated


def _rewrite_assignment_window(value: object) -> None:
    """Rewrite a known legacy ID in an analysis assignment window."""

    if not isinstance(value, dict):
        return
    _rewrite_legacy_material_id(value.get("window"))


def _rewrite_legacy_material_id(value: object) -> None:
    """Rewrite only material IDs whose canonical database identity changed."""

    if not isinstance(value, dict):
        return
    material_id = value.get("material_id")
    if not isinstance(material_id, str):
        return
    canonical_id = {
        "gaas": "gaas_300k",
        "algaas_al040": "algaas_al040_300k",
    }.get(material_id)
    if canonical_id is not None:
        value["material_id"] = canonical_id


class ProjectPersistence:
    """Read and atomically write complete ``.plproj`` project files.

    Loading is transactional with respect to application state: this service
    constructs and validates a separate :class:`PLProject` and never mutates a
    caller's current project. The caller replaces its current model only after
    :meth:`load` returns successfully.

    ``migrations`` maps a source schema version to a function producing the next
    version. This is the extension point used when future releases increment the
    project schema.
    """

    def __init__(self, migrations: Mapping[int, Migration] | None = None) -> None:
        self._migrations = _default_migrations()
        if migrations is not None:
            self._migrations.update(migrations)

    def save(self, project: PLProject, path: Path) -> None:
        """Atomically save a project as indented UTF-8 JSON."""

        target = _project_path(path)
        try:
            project.validate()
            payload = _project_to_payload(project)
            serialized = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ProjectPersistenceError(
                f"Project contains data that cannot be saved: {target}",
                code="E_PROJECT_INVALID",
                detail=str(exc),
            ) from exc

        temporary_path: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(serialized)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
        except OSError as exc:
            raise ProjectPersistenceError(
                f"Unable to save project: {target}",
                code="E_PROJECT_SAVE",
                detail=str(exc),
            ) from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                with suppress(OSError):
                    temporary_path.unlink()

    def load(self, path: Path) -> PLProject:
        """Load and fully validate a new project without mutating current state."""

        source = _project_path(path)
        try:
            with source.open("r", encoding="utf-8") as stream:
                payload = json.load(stream, parse_constant=_reject_json_constant)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProjectPersistenceError(
                f"Unable to read project: {source}",
                code="E_PROJECT_READ",
                detail=str(exc),
            ) from exc

        if not isinstance(payload, dict):
            raise ProjectPersistenceError(
                f"Project root must be a JSON object: {source}",
                code="E_PROJECT_FORMAT",
            )

        migrated = self._migrate(payload)
        try:
            return _project_from_payload(migrated)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectPersistenceError(
                f"Invalid project data: {source}",
                code="E_PROJECT_FORMAT",
                detail=str(exc),
            ) from exc

    def _migrate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return a current-schema copy by applying registered migrations."""

        migrated = copy.deepcopy(payload)
        version = _schema_version(migrated)
        if version > PROJECT_SCHEMA_VERSION:
            raise UnsupportedProjectVersionError(
                (
                    f"Project schema {version} is newer than supported schema "
                    f"{PROJECT_SCHEMA_VERSION}."
                ),
                code="E_PROJECT_VERSION_NEWER",
            )
        while version < PROJECT_SCHEMA_VERSION:
            migration = self._migrations.get(version)
            if migration is None:
                raise UnsupportedProjectVersionError(
                    f"No migration is available for project schema {version}.",
                    code="E_PROJECT_VERSION_OLDER",
                )
            migrated = migration(copy.deepcopy(migrated))
            if not isinstance(migrated, dict):
                raise ProjectPersistenceError(
                    f"Migration for schema {version} did not return an object.",
                    code="E_PROJECT_MIGRATION",
                )
            next_version = _schema_version(migrated)
            if next_version != version + 1:
                raise ProjectPersistenceError(
                    (
                        f"Migration for schema {version} must produce schema "
                        f"{version + 1}, got {next_version}."
                    ),
                    code="E_PROJECT_MIGRATION",
                )
            version = next_version
        return migrated


def save_project(project: PLProject, path: Path) -> None:
    """Save with the default migration registry."""

    ProjectPersistence().save(project, path)


def load_project(path: Path) -> PLProject:
    """Load with the default migration registry."""

    return ProjectPersistence().load(path)


def _project_to_payload(project: PLProject) -> dict[str, JSONValue]:
    return {
        "format_id": PROJECT_FORMAT_ID,
        "schema_version": PROJECT_SCHEMA_VERSION,
        "project": {
            "layers": [_layer_to_payload(layer) for layer in project.layers],
            "material_windows": [
                _material_window_to_payload(window) for window in project.material_windows
            ],
            "workspace": _workspace_to_payload(project.workspace),
            "analysis_results": {
                "raw_peak": {
                    spectrum_id: [
                        {
                            "window": {
                                "material_id": analysis.window.material_id,
                                "material_name": analysis.window.material_name,
                                "min_nm": analysis.window.min_nm,
                                "max_nm": analysis.window.max_nm,
                            },
                            "result": _peak_analysis_to_payload(analysis.result),
                        }
                        for analysis in analyses
                    ]
                    for spectrum_id, analyses in (project.workspace.material_peak_results.items())
                },
                "fit": _validated_json_object(project.fit_results, "fit_results"),
            },
            "extensions": _validated_json_object(project.extensions, "extensions"),
        },
    }


def _project_from_payload(payload: dict[str, Any]) -> PLProject:
    if payload.get("format_id") != PROJECT_FORMAT_ID:
        raise ValueError("Unknown or missing project format_id.")
    if _schema_version(payload) != PROJECT_SCHEMA_VERSION:
        raise ValueError("Project payload was not migrated to the current schema.")
    project_payload = _object(payload["project"], "project")
    workspace_payload = _object(project_payload["workspace"], "project.workspace")
    workspace = _workspace_from_payload(workspace_payload)

    analysis = _object(
        project_payload.get("analysis_results", {}),
        "project.analysis_results",
    )
    raw_peak = _object(analysis.get("raw_peak", {}), "analysis_results.raw_peak")
    decoded_material_results: dict[str, tuple[MaterialPeakAnalysis, ...]] = {}
    legacy_results: dict[str, PeakAnalysisResult] = {}
    for spectrum_id_value, encoded_result in raw_peak.items():
        spectrum_id = _text(spectrum_id_value, "raw peak spectrum ID")
        if isinstance(encoded_result, list):
            analyses: list[MaterialPeakAnalysis] = []
            for item in encoded_result:
                analysis_payload = _object(item, f"raw peak analysis {spectrum_id}")
                window_payload = _object(
                    analysis_payload["window"],
                    f"raw peak window {spectrum_id}",
                )
                analyses.append(
                    MaterialPeakAnalysis(
                        window=MaterialSearchWindow(
                            material_id=_text(
                                window_payload["material_id"],
                                "material_id",
                            ),
                            material_name=_text(
                                window_payload["material_name"],
                                "material_name",
                            ),
                            min_nm=_finite_float(window_payload["min_nm"], "min_nm"),
                            max_nm=_finite_float(window_payload["max_nm"], "max_nm"),
                        ),
                        result=_peak_analysis_from_payload(
                            _object(
                                analysis_payload["result"],
                                f"raw peak result {spectrum_id}",
                            )
                        ),
                    )
                )
            decoded_material_results[spectrum_id] = tuple(analyses)
        else:
            legacy_results[spectrum_id] = _peak_analysis_from_payload(
                _object(encoded_result, f"raw peak result {spectrum_id}")
            )
    if legacy_results:
        spectra_by_id = {spectrum.spectrum_id: spectrum for spectrum in workspace.spectra}
        for spectrum_id, result in legacy_results.items():
            spectrum = spectra_by_id[spectrum_id]
            decoded_material_results[spectrum_id] = (
                MaterialPeakAnalysis(
                    window=MaterialSearchWindow(
                        material_id="custom",
                        material_name="Custom",
                        min_nm=float(spectrum.wavelength_nm[0]),
                        max_nm=float(spectrum.wavelength_nm[-1]),
                    ),
                    result=result,
                ),
            )
    if decoded_material_results:
        workspace.set_material_peak_results(decoded_material_results)

    layers_payload = _array(project_payload.get("layers", []), "project.layers")
    windows_payload = _array(
        project_payload.get("material_windows", []),
        "project.material_windows",
    )
    fit_results = _validated_json_object(analysis.get("fit", {}), "fit_results")
    extensions = _validated_json_object(
        project_payload.get("extensions", {}),
        "extensions",
    )
    return PLProject(
        workspace=workspace,
        layers=[_layer_from_payload(_object(item, "layer")) for item in layers_payload],
        material_windows=[
            _material_window_from_payload(_object(item, "material window"))
            for item in windows_payload
        ],
        fit_results=fit_results,
        extensions=extensions,
    )


def _workspace_to_payload(workspace: Workspace) -> dict[str, JSONValue]:
    settings = workspace.plot_settings
    return {
        "plot_settings": {
            "amplitude_mode": settings.amplitude_mode.value,
            "offset_enabled": settings.offset_enabled,
            "y_scale": settings.y_scale.value,
            "legend_visible": settings.legend_visible,
            "grid_visible": settings.grid_visible,
        },
        "spectra": [_spectrum_to_payload(spectrum) for spectrum in workspace.spectra],
    }


def _workspace_from_payload(payload: dict[str, Any]) -> Workspace:
    settings_payload = _object(payload["plot_settings"], "workspace.plot_settings")
    settings = PlotDisplaySettings(
        amplitude_mode=AmplitudeMode(_text(settings_payload["amplitude_mode"], "amplitude_mode")),
        offset_enabled=_boolean(
            settings_payload["offset_enabled"],
            "offset_enabled",
        ),
        y_scale=AxisScale(_text(settings_payload["y_scale"], "y_scale")),
        legend_visible=_boolean(
            settings_payload["legend_visible"],
            "legend_visible",
        ),
        grid_visible=_boolean(settings_payload["grid_visible"], "grid_visible"),
    )
    spectra_payload = _array(payload["spectra"], "workspace.spectra")
    spectra = [_spectrum_from_payload(_object(item, "spectrum")) for item in spectra_payload]
    identifiers = [spectrum.spectrum_id for spectrum in spectra]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Spectrum IDs must be unique within a project.")
    workspace = Workspace(settings)
    workspace.add_spectra(spectra)
    return workspace


def _spectrum_to_payload(spectrum: SpectrumSeries) -> dict[str, JSONValue]:
    return {
        "spectrum_id": spectrum.spectrum_id,
        "name": spectrum.name,
        "wavelength_nm": spectrum.wavelength_nm.tolist(),
        "intensity_au": spectrum.intensity_au.tolist(),
        "source": {
            "file_path": spectrum.source.file_path,
            "sheet_name": spectrum.source.sheet_name,
            "wavelength_column": spectrum.source.wavelength_column,
            "intensity_column": spectrum.source.intensity_column,
        },
        "display": {
            "color": spectrum.display.color,
            "visible": spectrum.display.visible,
        },
        "diagnostics": list(spectrum.diagnostics),
    }


def _spectrum_from_payload(payload: dict[str, Any]) -> SpectrumSeries:
    source_payload = _object(payload["source"], "spectrum.source")
    display_payload = _object(payload["display"], "spectrum.display")
    sheet_name = source_payload.get("sheet_name")
    if sheet_name is not None:
        sheet_name = _text(sheet_name, "sheet_name", allow_empty=True)
    return SpectrumSeries(
        spectrum_id=_text(payload["spectrum_id"], "spectrum_id"),
        name=_text(payload["name"], "spectrum name"),
        wavelength_nm=_float_array(payload["wavelength_nm"], "wavelength_nm"),
        intensity_au=_float_array(payload["intensity_au"], "intensity_au"),
        source=SourceInfo(
            file_path=_text(source_payload["file_path"], "source.file_path"),
            sheet_name=sheet_name,
            wavelength_column=_text(
                source_payload["wavelength_column"],
                "source.wavelength_column",
            ),
            intensity_column=_text(
                source_payload["intensity_column"],
                "source.intensity_column",
            ),
        ),
        display=DisplayStyle(
            color=_text(display_payload["color"], "display.color", allow_empty=True),
            visible=_boolean(display_payload["visible"], "display.visible"),
        ),
        diagnostics=_text_tuple(payload.get("diagnostics", []), "diagnostics"),
    )


def _peak_analysis_to_payload(result: PeakAnalysisResult) -> dict[str, JSONValue]:
    return {
        "algorithm_version": result.algorithm_version,
        "effective_prominence_au": result.effective_prominence_au,
        "diagnostics": list(result.diagnostics),
        "peaks": [
            {
                "position_nm": peak.position_nm,
                "height_au": peak.height_au,
                "fwhm_nm": peak.fwhm_nm,
                "prominence_au": peak.prominence_au,
                "width_level_au": peak.width_level_au,
                "quality_flags": list(peak.quality_flags),
            }
            for peak in result.peaks
        ],
    }


def _peak_analysis_from_payload(payload: dict[str, Any]) -> PeakAnalysisResult:
    peaks_payload = _array(payload["peaks"], "raw peak peaks")
    return PeakAnalysisResult(
        peaks=tuple(_peak_from_payload(_object(peak, "raw peak")) for peak in peaks_payload),
        effective_prominence_au=_finite_float(
            payload["effective_prominence_au"],
            "effective_prominence_au",
        ),
        diagnostics=_text_tuple(payload.get("diagnostics", []), "diagnostics"),
        algorithm_version=_integer(
            payload.get("algorithm_version", 1),
            "algorithm_version",
            minimum=1,
        ),
    )


def _peak_from_payload(payload: dict[str, Any]) -> PeakResult:
    return PeakResult(
        position_nm=_finite_float(payload["position_nm"], "position_nm"),
        height_au=_finite_float(payload["height_au"], "height_au"),
        fwhm_nm=_optional_finite_float(payload.get("fwhm_nm"), "fwhm_nm"),
        prominence_au=_finite_float(payload["prominence_au"], "prominence_au"),
        width_level_au=_optional_finite_float(
            payload.get("width_level_au"),
            "width_level_au",
        ),
        quality_flags=_text_tuple(
            payload.get("quality_flags", []),
            "quality_flags",
        ),
    )


def _layer_to_payload(layer: Layer) -> dict[str, JSONValue]:
    return {
        "layer_id": layer.layer_id,
        "material": layer.material,
        "thickness_nm": layer.thickness_nm,
        "composition": layer.composition,
        "doping_type": layer.doping_type,
        "doping_concentration_cm^-3": layer.doping_concentration_cm3,
    }


def _layer_from_payload(payload: dict[str, Any]) -> Layer:
    return Layer(
        layer_id=_text(payload["layer_id"], "layer_id"),
        material=_text(payload["material"], "material"),
        thickness_nm=_finite_float(payload["thickness_nm"], "thickness_nm"),
        composition=_text(
            payload.get("composition", ""),
            "composition",
            allow_empty=True,
        ),
        doping_type=_text(
            payload.get("doping_type", ""),
            "doping_type",
            allow_empty=True,
        ),
        doping_concentration_cm3=_optional_finite_float(
            payload.get("doping_concentration_cm^-3"),
            "doping_concentration_cm^-3",
        ),
    )


def _material_window_to_payload(
    window: MaterialWindowSnapshot,
) -> dict[str, JSONValue]:
    return {
        "material_id": window.material_id,
        "display_name": window.display_name,
        "minimum_nm": window.minimum_nm,
        "maximum_nm": window.maximum_nm,
        "selected": window.selected,
    }


def _material_window_from_payload(
    payload: dict[str, Any],
) -> MaterialWindowSnapshot:
    return MaterialWindowSnapshot(
        material_id=_text(payload["material_id"], "material_id"),
        display_name=_text(payload["display_name"], "display_name"),
        minimum_nm=_optional_finite_float(payload.get("minimum_nm"), "minimum_nm"),
        maximum_nm=_optional_finite_float(payload.get("maximum_nm"), "maximum_nm"),
        selected=_boolean(payload.get("selected", True), "selected"),
    )


def _project_path(path: Path) -> Path:
    target = Path(path)
    if target.suffix.casefold() != ".plproj":
        raise ProjectPersistenceError(
            "PL Analyzer Pro projects must use the .plproj extension.",
            code="E_PROJECT_EXTENSION",
        )
    return target


def _schema_version(payload: dict[str, Any]) -> int:
    try:
        value = payload["schema_version"]
    except KeyError as exc:
        raise ProjectPersistenceError(
            "Project schema_version is missing.",
            code="E_PROJECT_VERSION",
        ) from exc
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProjectPersistenceError(
            "Project schema_version must be a non-negative integer.",
            code="E_PROJECT_VERSION",
        )
    return value


def _object(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a JSON object.")
    return value


def _array(value: object, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be a JSON array.")
    return value


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be text.")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must not be empty.")
    return value


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be true or false.")
    return value


def _integer(value: object, field_name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{field_name} must be an integer of at least {minimum}.")
    return value


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number.")
    return number


def _optional_finite_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    return _finite_float(value, field_name)


def _float_array(value: object, field_name: str) -> np.ndarray[Any, np.dtype[np.float64]]:
    values = _array(value, field_name)
    return np.asarray(
        [_finite_float(item, f"{field_name} item") for item in values],
        dtype=np.float64,
    )


def _text_tuple(value: object, field_name: str) -> tuple[str, ...]:
    values = _array(value, field_name)
    return tuple(_text(item, f"{field_name} item", allow_empty=True) for item in values)


def _validated_json_object(value: object, field_name: str) -> dict[str, JSONValue]:
    candidate = _object(value, field_name)
    validated = _validated_json_value(candidate, field_name)
    if not isinstance(validated, dict):
        raise TypeError(f"{field_name} must be a JSON object.")
    return validated


def _validated_json_value(value: object, field_name: str) -> JSONValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains a non-finite number.")
        return value
    if isinstance(value, list):
        return [_validated_json_value(item, f"{field_name}[]") for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError(f"{field_name} contains a non-text object key.")
        return {
            key: _validated_json_value(item, f"{field_name}.{key}") for key, item in value.items()
        }
    raise TypeError(f"{field_name} contains a non-JSON value: {type(value).__name__}.")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON numeric constant: {value}")
