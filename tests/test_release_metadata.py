"""Release identity and bilingual PyInstaller metadata consistency tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from core import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.1.3"
EXPECTED_TARGETS = {
    "en-US": ("main.py", "version_info.txt"),
    "zh-CN": ("main_zh.py", "version_info_zh_CN.txt"),
}
EXPECTED_ORIGIN_COMMIT = "c34980b82947af3f82f7a9a4ff5692610ba5398f"


def test_core_and_spec_share_the_release_version() -> None:
    """The Python application and PyInstaller artifact names must not drift."""

    assignments = _literal_spec_assignments()

    assert __version__ == EXPECTED_VERSION
    assert assignments["PRODUCT_VERSION"] == EXPECTED_VERSION
    assert assignments["BUILD_TARGETS"] == EXPECTED_TARGETS
    assert assignments["BUILD_LANGUAGE_ENVIRONMENT_VARIABLE"] == "PL_ANALYZER_PRO_BUILD_LANGUAGE"


def test_windows_version_resources_match_each_release_artifact() -> None:
    """Both locale-specific Windows resources must describe the exact output."""

    for language, (_, version_file_name) in EXPECTED_TARGETS.items():
        resource_path = PROJECT_ROOT / "resources" / version_file_name
        resource_text = resource_path.read_text(encoding="utf-8")
        artifact_name = f"PL-Analyzer-Pro-v{EXPECTED_VERSION}-Windows-x64-{language}.exe"

        assert "filevers=(1, 1, 3, 0)" in resource_text
        assert "prodvers=(1, 1, 3, 0)" in resource_text
        assert _string_struct_value(resource_text, "FileVersion") == EXPECTED_VERSION
        assert _string_struct_value(resource_text, "ProductVersion") == EXPECTED_VERSION
        assert _string_struct_value(resource_text, "OriginalFilename") == artifact_name


def test_build_script_declares_bilingual_gates_and_manifest() -> None:
    """The checked-in release command must retain both targets and safety gates."""

    script = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8")

    assert 'ValidateSet("all", "en-US", "zh-CN")' in script
    assert "PL_ANALYZER_PRO_BUILD_LANGUAGE" in script
    assert "-m pytest" in script
    assert "-m ruff check ." in script
    assert "-m ruff format --check ." in script
    assert "PL_ANALYZER_PRO_SMOKE_EXIT_MS" in script
    assert "SHA256SUMS.txt" in script


def test_build_script_publishes_and_hashes_complete_origin_notices() -> None:
    """The public release must expose provenance, NOTICE, and the full license."""

    script = (PROJECT_ROOT / "build_release.ps1").read_text(encoding="utf-8")

    required_markers = (
        "THIRD-PARTY-NOTICES.txt",
        "quantized-lab Origin worksheet reader subset",
        "Upstream version: 0.11.0",
        EXPECTED_ORIGIN_COMMIT,
        "https://github.com/pquarterman17/quantized/tree/v0.11.0",
        "License: Apache License 2.0",
        "not GPL liborigin",
        "UPSTREAM.md",
        "NOTICE",
        "LICENSE",
        "$upstreamText",
        "$noticeText",
        "$licenseText",
        "$releaseAssetPaths = @($artifactPaths) + @($thirdPartyNoticesPath)",
        "foreach ($assetPath in ($releaseAssetPaths | Sort-Object))",
    )

    for marker in required_markers:
        assert marker in script

    assert "[System.IO.File]::ReadAllText" in script
    assert "----- UPSTREAM PROVENANCE AND MODIFICATION NOTES (UPSTREAM.md) -----" in script
    assert "----- UPSTREAM NOTICE -----" in script
    assert "----- APACHE LICENSE 2.0 -----" in script


def test_v113_release_documents_disclose_origin_scope_and_license() -> None:
    """Release-facing documents must retain the native-reader support boundary."""

    documents = (
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "docs" / "development.md",
        PROJECT_ROOT / "docs" / "release_v1.1.3.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in documents)

    required_markers = (
        "THIRD-PARTY-NOTICES.txt",
        "quantized-lab",
        "v0.11.0",
        EXPECTED_ORIGIN_COMMIT,
        "Apache-2.0",
        "liborigin",
        "Origin/COM",
        "worksheet",
        "float32",
        "OPJU",
    )
    for marker in required_markers:
        assert marker in combined


def _literal_spec_assignments() -> dict[str, object]:
    spec_path = PROJECT_ROOT / "PLAnalyzerPro.spec"
    module = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
    assignments: dict[str, object] = {}
    expected_names = {
        "PRODUCT_VERSION",
        "BUILD_TARGETS",
        "BUILD_LANGUAGE_ENVIRONMENT_VARIABLE",
    }
    for node in module.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in expected_names:
            assignments[target.id] = ast.literal_eval(node.value)
    return assignments


def _string_struct_value(resource_text: str, name: str) -> str:
    pattern = re.compile(
        rf'StringStruct\(\s*"{re.escape(name)}",\s*"([^"]+)"\s*,?\s*\)',
        re.DOTALL,
    )
    match = pattern.search(resource_text)
    assert match is not None, f"Missing StringStruct for {name}"
    return match.group(1)
