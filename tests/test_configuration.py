"""Configuration and material database validation tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.configuration import ApplicationSettings, MaterialDatabase, application_root
from core.errors import ConfigurationError
from core.models import AmplitudeMode


def test_default_configuration_and_material_windows_load() -> None:
    root = application_root()
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")

    assert settings.plot.amplitude_mode is AmplitudeMode.RAW
    assert materials.find("gaas_300k").default_peak_window_nm == (860.0, 900.0)
    assert materials.find("algaas_al040_300k").default_peak_window_nm == (
        620.0,
        670.0,
    )
    assert materials.find("ingaas_variable_composition").default_peak_window_nm is None
    assert materials.find("inp_300k").default_peak_window_nm == (890.0, 970.0)
    assert materials.find("gaas_300k").default_selected
    assert materials.database_version == "2026.07"
    assert materials.find("dbr_structure").references[0]["doi"] == "10.1016/j.jlumin.2006.01.303"
    assert any(
        reference.get("doi") == "10.1063/1.122534"
        for reference in materials.find("qd_laser_1300_active_region").references
    )


@pytest.mark.parametrize(
    "database_version",
    [None, "", " "],
    ids=["missing", "empty", "whitespace"],
)
def test_schema_v2_requires_database_version(
    tmp_path: Path,
    database_version: str | None,
) -> None:
    payload = _valid_v2_payload()
    if database_version is None:
        del payload["database_version"]
    else:
        payload["database_version"] = database_version

    error = _load_invalid_database(tmp_path, payload)

    assert error.detail is not None
    assert "database_version" in error.detail


@pytest.mark.parametrize(
    ("field_name", "value", "expected_detail"),
    [
        pytest.param("window_basis", "", "empty window_basis", id="window-basis"),
        pytest.param("window_basis", None, "empty window_basis", id="window-basis-null"),
        pytest.param("notes", " ", "empty notes", id="notes"),
        pytest.param(
            "references",
            [],
            "at least one reference is required",
            id="references",
        ),
    ],
)
def test_schema_v2_requires_scientific_metadata(
    tmp_path: Path,
    field_name: str,
    value: object,
    expected_detail: str,
) -> None:
    payload = _valid_v2_payload()
    payload["materials"][0][field_name] = value

    error = _load_invalid_database(tmp_path, payload)

    assert error.detail is not None
    assert expected_detail in error.detail


@pytest.mark.parametrize(
    ("reference", "expected_detail"),
    [
        pytest.param(
            {"doi": "10.1234/example", "basis": ""},
            "requires non-empty basis",
            id="empty-basis",
        ),
        pytest.param(
            {"basis": "Scientific basis."},
            "requires a DOI or https URL",
            id="missing-source",
        ),
        pytest.param(
            {"url": "http://example.test/paper", "basis": "Scientific basis."},
            "URL must use https",
            id="insecure-url",
        ),
    ],
)
def test_schema_v2_rejects_malformed_references(
    tmp_path: Path,
    reference: dict[str, str],
    expected_detail: str,
) -> None:
    payload = _valid_v2_payload()
    payload["materials"][0]["references"] = [reference]

    error = _load_invalid_database(tmp_path, payload)

    assert error.detail is not None
    assert expected_detail in error.detail


def test_schema_v2_accepts_https_reference_without_doi(tmp_path: Path) -> None:
    payload = _valid_v2_payload()
    payload["materials"][0]["references"] = [
        {
            "url": "https://example.test/material-paper",
            "basis": "Scientific source available by HTTPS.",
        }
    ]
    path = _write_database(tmp_path, payload)

    database = MaterialDatabase.from_json(path)

    assert (
        database.find("test_material").references[0]["url"] == "https://example.test/material-paper"
    )


def test_schema_v1_remains_compatible_without_v2_metadata(tmp_path: Path) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "materials": [
            {
                "id": "legacy_material",
                "display_name": "Legacy material",
                "default_peak_window_nm": {"min_nm": 800.0, "max_nm": 900.0},
            }
        ],
    }
    path = _write_database(tmp_path, payload)

    database = MaterialDatabase.from_json(path)

    assert database.schema_version == 1
    assert database.database_version is None
    assert database.find("legacy_material").window_basis == ""
    assert database.find("legacy_material").references == ()


def _valid_v2_payload() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "database_version": "test.1",
        "materials": [
            {
                "id": "test_material",
                "display_name": "Test material",
                "aliases": ["Test"],
                "category": "material",
                "default_selected": False,
                "reference_temperature_k": 300.0,
                "nominal_transition_ev": 1.5,
                "nominal_wavelength_nm": 826.6,
                "default_peak_window_nm": {
                    "min_nm": 800.0,
                    "max_nm": 850.0,
                },
                "extended_peak_window_nm": {
                    "min_nm": 780.0,
                    "max_nm": 870.0,
                },
                "window_basis": "Test window basis.",
                "notes": "Test scientific limitation.",
                "references": [
                    {
                        "doi": "10.1234/example",
                        "basis": "Test scientific source.",
                    }
                ],
            }
        ],
    }


def _load_invalid_database(
    tmp_path: Path,
    payload: dict[str, Any],
) -> ConfigurationError:
    path = _write_database(tmp_path, payload)
    with pytest.raises(ConfigurationError) as exc_info:
        MaterialDatabase.from_json(path)
    return exc_info.value


def _write_database(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "materials.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path
