"""Release identity and bilingual PyInstaller metadata consistency tests."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from core import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "1.1.1"
EXPECTED_TARGETS = {
    "en-US": ("main.py", "version_info.txt"),
    "zh-CN": ("main_zh.py", "version_info_zh_CN.txt"),
}


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

        assert "filevers=(1, 1, 1, 0)" in resource_text
        assert "prodvers=(1, 1, 1, 0)" in resource_text
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
