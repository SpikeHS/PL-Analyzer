"""PyInstaller one-file Windows release specification for PL Analyzer Pro."""

from pathlib import Path


project_root = Path(SPECPATH).resolve()
data_directories = ("config", "resources", "icons")
datas = []
for directory_name in data_directories:
    source_directory = project_root / directory_name
    if not source_directory.is_dir():
        raise FileNotFoundError(f"Required release directory is missing: {source_directory}")
    datas.append((str(source_directory), directory_name))

version_file = project_root / "resources" / "version_info.txt"
if not version_file.is_file():
    raise FileNotFoundError(f"Windows version resource is missing: {version_file}")

icon_file = project_root / "icons" / "pl_analyzer_pro.ico"
icon_argument = str(icon_file) if icon_file.is_file() else None

analysis = Analysis(
    [str(project_root / "main.py")],
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
    name="PL Analyzer Pro",
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
