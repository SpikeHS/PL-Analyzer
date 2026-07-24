"""PyInstaller one-file Windows release specification for PL Analyzer Pro."""

import os
from pathlib import Path


PRODUCT_VERSION = "1.1.1"
BUILD_TARGETS = {
    "en-US": ("main.py", "version_info.txt"),
    "zh-CN": ("main_zh.py", "version_info_zh_CN.txt"),
}
BUILD_LANGUAGE_ENVIRONMENT_VARIABLE = "PL_ANALYZER_PRO_BUILD_LANGUAGE"

project_root = Path(SPECPATH).resolve()
build_language = os.environ.get(BUILD_LANGUAGE_ENVIRONMENT_VARIABLE)
if build_language not in BUILD_TARGETS:
    supported_languages = ", ".join(BUILD_TARGETS)
    raise ValueError(
        f"{BUILD_LANGUAGE_ENVIRONMENT_VARIABLE} must be one of: "
        f"{supported_languages}; got {build_language!r}"
    )

entry_point_name, version_file_name = BUILD_TARGETS[build_language]
entry_point = project_root / entry_point_name
if not entry_point.is_file():
    raise FileNotFoundError(f"Application entry point is missing: {entry_point}")

data_directories = ("config", "resources", "icons")
datas = []
for directory_name in data_directories:
    source_directory = project_root / directory_name
    if not source_directory.is_dir():
        raise FileNotFoundError(f"Required release directory is missing: {source_directory}")
    datas.append((str(source_directory), directory_name))

version_file = project_root / "resources" / version_file_name
if not version_file.is_file():
    raise FileNotFoundError(f"Windows version resource is missing: {version_file}")

artifact_name = (
    f"PL-Analyzer-Pro-v{PRODUCT_VERSION}-Windows-x64-{build_language}"
)
icon_file = project_root / "icons" / "pl_analyzer_pro.ico"
icon_argument = str(icon_file) if icon_file.is_file() else None

analysis = Analysis(
    [str(entry_point)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=artifact_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_argument,
    version=str(version_file),
)
