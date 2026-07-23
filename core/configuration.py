"""Validated loading of application settings and material peak windows."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.errors import ConfigurationError
from core.models import AmplitudeMode, AxisScale, PlotDisplaySettings


@dataclass(frozen=True, slots=True)
class AnalysisDefaults:
    """Default controls for raw peak detection."""

    relative_prominence: float
    noise_sigma_factor: float
    min_distance_nm: float
    max_peaks: int
    gap_factor: float


@dataclass(frozen=True, slots=True)
class ApplicationSettings:
    """Validated application configuration."""

    analysis: AnalysisDefaults
    plot: PlotDisplaySettings

    @classmethod
    def from_json(cls, path: Path) -> ApplicationSettings:
        """Load settings from a JSON file."""

        payload = _read_json(path)
        try:
            if payload["schema_version"] != 1:
                raise ValueError("unsupported schema version")
            analysis = payload["analysis"]
            plot = payload["plot"]
            defaults = AnalysisDefaults(
                relative_prominence=float(analysis["relative_prominence"]),
                noise_sigma_factor=float(analysis["noise_sigma_factor"]),
                min_distance_nm=float(analysis["min_distance_nm"]),
                max_peaks=int(analysis["max_peaks"]),
                gap_factor=float(analysis["gap_factor"]),
            )
            plot_settings = PlotDisplaySettings(
                amplitude_mode=AmplitudeMode(plot["amplitude_mode"]),
                offset_enabled=bool(plot["offset_enabled"]),
                y_scale=AxisScale(plot["y_scale"]),
                legend_visible=bool(plot["legend_visible"]),
                grid_visible=bool(plot["grid_visible"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid application settings: {path}",
                code="E_CONFIG_SETTINGS",
                detail=str(exc),
            ) from exc

        if (
            not math.isfinite(defaults.relative_prominence)
            or not 0 <= defaults.relative_prominence <= 1
            or not math.isfinite(defaults.noise_sigma_factor)
            or defaults.noise_sigma_factor < 0
            or not math.isfinite(defaults.min_distance_nm)
            or defaults.min_distance_nm < 0
            or not math.isfinite(defaults.gap_factor)
        ):
            raise ConfigurationError(
                "Peak-analysis defaults contain a non-finite or negative value.",
                code="E_CONFIG_SETTINGS",
            )
        if defaults.max_peaks < 1 or defaults.gap_factor <= 1:
            raise ConfigurationError(
                "Peak defaults contain an invalid limit.",
                code="E_CONFIG_SETTINGS",
            )
        return cls(analysis=defaults, plot=plot_settings)


@dataclass(frozen=True, slots=True)
class MaterialRecord:
    """One configurable material and its optional default search window."""

    material_id: str
    display_name: str
    aliases: tuple[str, ...]
    category: str
    default_selected: bool
    reference_temperature_k: float | None
    nominal_transition_ev: float | None
    nominal_wavelength_nm: float | None
    default_peak_window_nm: tuple[float, float] | None
    extended_peak_window_nm: tuple[float, float] | None
    window_basis: str
    notes: str
    references: tuple[dict[str, str], ...]


class MaterialDatabase:
    """Read-only material catalog loaded from versioned JSON."""

    def __init__(
        self,
        materials: tuple[MaterialRecord, ...],
        schema_version: int,
        database_version: str | None = None,
    ) -> None:
        if not materials:
            raise ConfigurationError(
                "The material database is empty.",
                code="E_CONFIG_MATERIALS",
            )
        self._materials = materials
        self.schema_version = schema_version
        self.database_version = database_version

    @property
    def materials(self) -> tuple[MaterialRecord, ...]:
        """Return catalog entries in configured display order."""

        return self._materials

    def find(self, material_id: str) -> MaterialRecord:
        """Return a material by stable ID."""

        for material in self._materials:
            if material.material_id == material_id:
                return material
        raise ConfigurationError(
            f"Unknown material: {material_id}",
            code="E_CONFIG_MATERIAL_UNKNOWN",
        )

    @classmethod
    def from_json(cls, path: Path) -> MaterialDatabase:
        """Load and validate a material database."""

        payload = _read_json(path)
        try:
            schema_version = int(payload["schema_version"])
            if schema_version not in {1, 2}:
                raise ValueError("unsupported schema version")
            database_version = _material_database_version(payload, schema_version)
            records: list[MaterialRecord] = []
            seen_ids: set[str] = set()
            for item in payload["materials"]:
                material_id = str(item["id"]).strip()
                if not material_id or material_id in seen_ids:
                    raise ValueError(f"duplicate or empty material id: {material_id}")
                seen_ids.add(material_id)
                display_name = str(item["display_name"]).strip()
                if not display_name:
                    raise ValueError(f"empty display name for {material_id}")
                aliases = item.get("aliases", [])
                if not isinstance(aliases, list):
                    raise ValueError(f"aliases must be an array for {material_id}")
                category = str(item.get("category", "material")).strip()
                if not category:
                    raise ValueError(f"empty category for {material_id}")
                window_payload = item.get("default_peak_window_nm")
                window: tuple[float, float] | None = None
                if window_payload is not None:
                    minimum = float(window_payload["min_nm"])
                    maximum = float(window_payload["max_nm"])
                    if (
                        not math.isfinite(minimum)
                        or not math.isfinite(maximum)
                        or minimum <= 0
                        or minimum >= maximum
                    ):
                        raise ValueError(f"invalid peak window for {material_id}")
                    window = (minimum, maximum)
                extended_payload = item.get("extended_peak_window_nm")
                extended_window: tuple[float, float] | None = None
                if extended_payload is not None:
                    extended_minimum = float(extended_payload["min_nm"])
                    extended_maximum = float(extended_payload["max_nm"])
                    if (
                        not math.isfinite(extended_minimum)
                        or not math.isfinite(extended_maximum)
                        or extended_minimum <= 0
                        or extended_minimum >= extended_maximum
                    ):
                        raise ValueError(f"invalid extended peak window for {material_id}")
                    extended_window = (extended_minimum, extended_maximum)
                default_selected_value = item.get(
                    "default_selected",
                    material_id in {"gaas", "algaas_al040"},
                )
                if not isinstance(default_selected_value, bool):
                    raise ValueError(f"default_selected must be boolean for {material_id}")
                if default_selected_value and window is None:
                    raise ValueError(f"default-selected material requires a window: {material_id}")
                window_basis = _material_text_field(
                    item,
                    "window_basis",
                    material_id,
                    schema_version,
                )
                notes = _material_text_field(
                    item,
                    "notes",
                    material_id,
                    schema_version,
                )
                references = _material_references(item, material_id, schema_version)
                records.append(
                    MaterialRecord(
                        material_id=material_id,
                        display_name=display_name,
                        aliases=tuple(str(alias) for alias in aliases),
                        category=category,
                        default_selected=default_selected_value,
                        reference_temperature_k=_optional_float(
                            item.get("reference_temperature_k")
                        ),
                        nominal_transition_ev=_optional_float(item.get("nominal_transition_ev")),
                        nominal_wavelength_nm=_optional_float(item.get("nominal_wavelength_nm")),
                        default_peak_window_nm=window,
                        extended_peak_window_nm=extended_window,
                        window_basis=window_basis,
                        notes=notes,
                        references=references,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"Invalid material database: {path}",
                code="E_CONFIG_MATERIALS",
                detail=str(exc),
            ) from exc
        return cls(tuple(records), schema_version, database_version)


def application_root() -> Path:
    """Return the source or PyInstaller data root."""

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Unable to read configuration: {path}",
            code="E_CONFIG_READ",
            detail=str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(
            f"Configuration root must be an object: {path}",
            code="E_CONFIG_FORMAT",
        )
    return payload


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("optional physical metadata must be positive and finite")
    return number


def _material_database_version(
    payload: dict[str, Any],
    schema_version: int,
) -> str | None:
    value = payload.get("database_version")
    if value is None:
        if schema_version >= 2:
            raise ValueError("database_version is required for schema v2")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("database_version must be a non-empty string")
    return value.strip()


def _material_text_field(
    item: dict[str, Any],
    field_name: str,
    material_id: str,
    schema_version: int,
) -> str:
    value = item.get(field_name, "")
    if schema_version >= 2 and (not isinstance(value, str) or not value.strip()):
        raise ValueError(f"empty {field_name} for {material_id}")
    return str(value).strip()


def _material_references(
    item: dict[str, Any],
    material_id: str,
    schema_version: int,
) -> tuple[dict[str, str], ...]:
    references = item.get("references", [])
    if not isinstance(references, list) or any(
        not isinstance(reference, dict) for reference in references
    ):
        raise ValueError(f"invalid references for {material_id}")
    if schema_version >= 2 and not references:
        raise ValueError(f"at least one reference is required for {material_id}")

    normalized: list[dict[str, str]] = []
    for reference_index, reference in enumerate(references, start=1):
        normalized_reference = {str(key): str(value).strip() for key, value in reference.items()}
        if schema_version >= 2:
            basis = _reference_field(reference, "basis", material_id, reference_index)
            doi = _reference_field(
                reference,
                "doi",
                material_id,
                reference_index,
                required=False,
            )
            url = _reference_field(
                reference,
                "url",
                material_id,
                reference_index,
                required=False,
            )
            if url and not url.startswith("https://"):
                raise ValueError(
                    f"reference {reference_index} URL must use https for {material_id}"
                )
            if not doi and not url:
                raise ValueError(
                    f"reference {reference_index} requires a DOI or https URL for {material_id}"
                )
            normalized_reference["basis"] = basis
            if doi:
                normalized_reference["doi"] = doi
            if url:
                normalized_reference["url"] = url
        normalized.append(normalized_reference)
    return tuple(normalized)


def _reference_field(
    reference: dict[str, Any],
    field_name: str,
    material_id: str,
    reference_index: int,
    *,
    required: bool = True,
) -> str:
    value = reference.get(field_name)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip():
        if required:
            raise ValueError(
                f"reference {reference_index} requires non-empty {field_name} for {material_id}"
            )
        if value is not None:
            raise ValueError(
                f"reference {reference_index} {field_name} must be a string for {material_id}"
            )
        return ""
    return value.strip()
