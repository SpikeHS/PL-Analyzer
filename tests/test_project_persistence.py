"""Round-trip and failure-safety tests for PL project persistence."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from core.models import (
    AmplitudeMode,
    AxisScale,
    DisplayStyle,
    PeakAnalysisResult,
    PeakResult,
    PlotDisplaySettings,
    SourceInfo,
    SpectrumSeries,
)
from core.persistence import (
    PROJECT_SCHEMA_VERSION,
    ProjectPersistence,
    ProjectPersistenceError,
    UnsupportedProjectVersionError,
)
from core.project import Layer, MaterialWindowSnapshot, PLProject
from core.workspace import Workspace


def _project() -> PLProject:
    workspace = Workspace(
        PlotDisplaySettings(
            amplitude_mode=AmplitudeMode.NORMALIZE,
            offset_enabled=True,
            y_scale=AxisScale.LOG,
            legend_visible=False,
            grid_visible=False,
        )
    )
    workspace.add_spectra(
        [
            SpectrumSeries(
                spectrum_id="AGA017::Sheet1",
                name="AGA017 / Sheet1",
                wavelength_nm=np.asarray([620.0, 645.5, 670.0]),
                intensity_au=np.asarray([1.25, 42.0, 2.5]),
                source=SourceInfo(
                    file_path="C:/实验数据/AGA017.xlsx",
                    sheet_name="PL 300 K",
                    wavelength_column="波长 (nm)",
                    intensity_column="Intensity",
                ),
                display=DisplayStyle(color="#12abef", visible=False),
                diagnostics=("sorted wavelength",),
            )
        ]
    )
    workspace.set_peak_results(
        {
            "AGA017::Sheet1": PeakAnalysisResult(
                peaks=(
                    PeakResult(
                        position_nm=645.5,
                        height_au=42.0,
                        fwhm_nm=18.25,
                        prominence_au=40.75,
                        width_level_au=21.625,
                        quality_flags=("interpolated_width",),
                    ),
                ),
                effective_prominence_au=0.42,
                diagnostics=("single peak",),
                algorithm_version=1,
            )
        }
    )
    return PLProject(
        workspace=workspace,
        layers=[
            Layer(
                layer_id="cap",
                material="GaAs",
                thickness_nm=5.0,
                composition="-",
                doping_type="Si",
                doping_concentration_cm3=1.0e18,
            ),
            Layer(
                layer_id="barrier",
                material="AlGaAs",
                thickness_nm=400.0,
                composition="Al=0.40",
                doping_type="Si",
                doping_concentration_cm3=1.3e17,
            ),
        ],
        material_windows=[
            MaterialWindowSnapshot("gaas_300k", "GaAs", 860.0, 900.0),
            MaterialWindowSnapshot(
                "algaas_al040_300k",
                "Al₀.₄Ga₀.₆As",
                620.0,
                670.0,
            ),
        ],
        fit_results={
            "AGA017::Sheet1": {
                "schema_version": 1,
                "models": [{"kind": "voigt", "parameters": [1.0, 2.0]}],
            }
        },
        extensions={"operator_notes": "室温 PL"},
    )


def test_project_round_trip_preserves_layers_arrays_and_analysis(
    tmp_path: Path,
) -> None:
    target = tmp_path / "complete.plproj"
    persistence = ProjectPersistence()
    original = _project()

    persistence.save(original, target)
    restored = persistence.load(target)

    assert restored is not original
    assert [layer.material for layer in restored.layers] == ["GaAs", "AlGaAs"]
    assert restored.layers[1].composition == "Al=0.40"
    assert restored.layers[1].doping_concentration_cm3 == pytest.approx(1.3e17)
    assert [window.material_id for window in restored.material_windows] == [
        "gaas_300k",
        "algaas_al040_300k",
    ]
    spectrum = restored.workspace.spectra[0]
    np.testing.assert_array_equal(
        spectrum.wavelength_nm,
        np.asarray([620.0, 645.5, 670.0]),
    )
    np.testing.assert_array_equal(
        spectrum.intensity_au,
        np.asarray([1.25, 42.0, 2.5]),
    )
    assert not spectrum.wavelength_nm.flags.writeable
    assert spectrum.display.color == "#12abef"
    assert spectrum.display.visible is False
    assert spectrum.source.file_path == "C:/实验数据/AGA017.xlsx"
    settings = restored.workspace.plot_settings
    assert settings.amplitude_mode is AmplitudeMode.NORMALIZE
    assert settings.offset_enabled is True
    assert settings.y_scale is AxisScale.LOG
    assert settings.legend_visible is False
    assert settings.grid_visible is False
    peak = restored.workspace.peak_results["AGA017::Sheet1"].peaks[0]
    assert peak.position_nm == pytest.approx(645.5)
    assert peak.fwhm_nm == pytest.approx(18.25)
    assert restored.fit_results == original.fit_results
    assert restored.extensions == {"operator_notes": "室温 PL"}

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == PROJECT_SCHEMA_VERSION
    assert payload["project"]["layers"][0]["doping_concentration_cm^-3"] == 1.0e18
    assert payload["project"]["analysis_results"]["raw_peak"]
    assert payload["project"]["analysis_results"]["fit"]


def test_corrupt_file_does_not_mutate_current_project(tmp_path: Path) -> None:
    current = _project()
    original_spectrum = current.workspace.spectra[0]
    original_layers = list(current.layers)
    corrupt = tmp_path / "corrupt.plproj"
    corrupt.write_text('{"schema_version": 1, "project": ', encoding="utf-8")

    with pytest.raises(ProjectPersistenceError) as error:
        ProjectPersistence().load(corrupt)

    assert error.value.code == "E_PROJECT_READ"
    assert current.workspace.spectra[0] is original_spectrum
    assert current.layers == original_layers
    assert current.workspace.peak_results["AGA017::Sheet1"].peaks[0].height_au == 42.0


def test_newer_project_schema_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "future.plproj"
    persistence = ProjectPersistence()
    persistence.save(_project(), target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = PROJECT_SCHEMA_VERSION + 1
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(UnsupportedProjectVersionError) as error:
        persistence.load(target)

    assert error.value.code == "E_PROJECT_VERSION_NEWER"


def test_registered_migration_advances_exactly_one_schema(tmp_path: Path) -> None:
    target = tmp_path / "legacy.plproj"
    ProjectPersistence().save(_project(), target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = 0
    target.write_text(json.dumps(payload), encoding="utf-8")

    def migrate_zero_to_one(legacy: dict[str, object]) -> dict[str, object]:
        legacy["schema_version"] = 1
        return legacy

    restored = ProjectPersistence(migrations={0: migrate_zero_to_one}).load(target)

    assert restored.layers[0].material == "GaAs"


def test_v1_migration_updates_every_legacy_material_reference(
    tmp_path: Path,
) -> None:
    target = tmp_path / "v1-material-ids.plproj"
    persistence = ProjectPersistence()
    persistence.save(_project(), target)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["schema_version"] = 1

    material_windows = payload["project"]["material_windows"]
    material_windows[0].update(
        {
            "material_id": "gaas",
            "minimum_nm": 862.5,
            "maximum_nm": 897.5,
            "selected": False,
        }
    )
    material_windows[1].update(
        {
            "material_id": "algaas_al040",
            "minimum_nm": 624.0,
            "maximum_nm": 666.0,
            "selected": True,
        }
    )
    material_windows.append(
        {
            "material_id": "custom_qd",
            "display_name": "Custom QD",
            "minimum_nm": 980.0,
            "maximum_nm": 1100.0,
            "selected": True,
        }
    )

    raw_peak = payload["project"]["analysis_results"]["raw_peak"]
    raw_assignment = raw_peak["AGA017::Sheet1"][0]
    raw_assignment["window"]["material_id"] = "gaas"
    payload["project"]["analysis_results"]["fit"] = {
        "schema_version": 1,
        "assignments": [
            {
                "window": {
                    "material_id": "algaas_al040",
                    "material_name": "AlGaAs",
                    "min_nm": 624.0,
                    "max_nm": 666.0,
                }
            },
            {
                "window": {
                    "material_id": "custom_qd",
                    "material_name": "Custom QD",
                    "min_nm": 980.0,
                    "max_nm": 1100.0,
                }
            },
        ],
    }
    target.write_text(json.dumps(payload), encoding="utf-8")

    restored = persistence.load(target)

    assert [
        (
            window.material_id,
            window.minimum_nm,
            window.maximum_nm,
            window.selected,
        )
        for window in restored.material_windows
    ] == [
        ("gaas_300k", 862.5, 897.5, False),
        ("algaas_al040_300k", 624.0, 666.0, True),
        ("custom_qd", 980.0, 1100.0, True),
    ]
    restored_raw = restored.workspace.material_peak_results["AGA017::Sheet1"]
    assert restored_raw[0].window.material_id == "gaas_300k"
    fit_assignments = restored.fit_results["assignments"]
    assert fit_assignments[0]["window"]["material_id"] == "algaas_al040_300k"
    assert fit_assignments[1]["window"]["material_id"] == "custom_qd"


def test_non_json_fit_extension_is_rejected_without_replacing_file(
    tmp_path: Path,
) -> None:
    target = tmp_path / "atomic.plproj"
    persistence = ProjectPersistence()
    project = _project()
    persistence.save(project, target)
    original_bytes = target.read_bytes()
    project.fit_results["invalid"] = {"array": np.asarray([1.0, 2.0])}

    with pytest.raises(ProjectPersistenceError) as error:
        persistence.save(project, target)

    assert error.value.code == "E_PROJECT_INVALID"
    assert target.read_bytes() == original_bytes


def test_layer_rejects_invalid_physical_values() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        Layer(material="GaAs", thickness_nm=0)
    with pytest.raises(ValueError, match="must not be negative"):
        Layer(
            material="GaAs",
            thickness_nm=5,
            doping_concentration_cm3=-1,
        )
