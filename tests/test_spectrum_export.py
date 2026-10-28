"""Checked-curve Excel export tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from core.errors import ExportError
from core.models import PeakTableRecord, SourceInfo, SpectrumSeries
from export.spectrum_table import SpectrumTableExporter


def _spectrum(
    identifier: str,
    name: str,
    *,
    wavelengths: tuple[float, ...] = (860.0, 870.0, 880.0),
    intensities: tuple[float, ...] = (1.5, 5.25, 2.0),
    sheet_name: str | None = None,
    metadata: tuple[tuple[str, str], ...] = (),
) -> SpectrumSeries:
    return SpectrumSeries(
        spectrum_id=identifier,
        name=name,
        wavelength_nm=np.asarray(wavelengths),
        intensity_au=np.asarray(intensities),
        source=SourceInfo(
            file_path=f"C:/data/{identifier}.opj",
            sheet_name=sheet_name,
            wavelength_column="Wavelength",
            intensity_column="Intensity",
            metadata=metadata,
        ),
    )


def _peak(
    spectrum_id: str,
    sample_name: str,
    position_nm: float,
    *,
    included: bool,
) -> PeakTableRecord:
    return PeakTableRecord(
        sample_name=sample_name,
        material_names=("GaAs",),
        peak_number=1,
        position_nm=position_nm,
        height_au=5.25,
        fwhm_nm=8.0,
        prominence_au=3.75,
        quality_flags=(),
        spectrum_id=spectrum_id,
        included=included,
    )


def test_workbook_contains_complete_curve_data_and_accepted_peaks(
    tmp_path: Path,
) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    spectra = (
        _spectrum(
            "one",
            "AGA017",
            sheet_name="PL 300 K",
            metadata=(("Laser", "532 nm"), ("Power", "12 mW")),
        ),
        _spectrum("two", "AGA018", intensities=(0.5, 2.0, 0.75)),
    )
    peaks = (
        _peak("one", "AGA017", 870.0, included=True),
        _peak("two", "AGA018", 870.0, included=False),
    )
    target = tmp_path / "curves.xlsx"

    SpectrumTableExporter().export(spectra, target, peak_records=peaks)

    workbook = openpyxl.load_workbook(target, data_only=True)
    try:
        assert workbook.sheetnames == ["AGA017", "AGA018", "Peaks"]

        curve = workbook["AGA017"]
        assert [cell.value for cell in curve[1]] == ["Wavelength (nm)", "Intensity (a.u.)"]
        assert curve.max_row == 4
        assert [row[0].value for row in curve.iter_rows(min_row=2)] == [860.0, 870.0, 880.0]
        assert [row[1].value for row in curve.iter_rows(min_row=2)] == [1.5, 5.25, 2.0]

        second = workbook["AGA018"]
        assert [row[1].value for row in second.iter_rows(min_row=2)] == [0.5, 2.0, 0.75]

        peak_sheet = workbook["Peaks"]
        assert peak_sheet.max_row == 2
        assert peak_sheet["A2"].value == "AGA017"
        assert peak_sheet["D2"].value == pytest.approx(870.0)
    finally:
        workbook.close()


def test_export_has_no_overview_or_summary_sheet(tmp_path: Path) -> None:
    """The workbook must contain curve data only, not a basic-information sheet."""

    openpyxl = pytest.importorskip("openpyxl")
    target = tmp_path / "data-only.xlsx"

    SpectrumTableExporter().export((_spectrum("one", "AGA017"),), target)

    workbook = openpyxl.load_workbook(target)
    try:
        assert workbook.sheetnames == ["AGA017"]
        header = [cell.value for cell in workbook["AGA017"][1]]
        assert header == ["Wavelength (nm)", "Intensity (a.u.)"]
    finally:
        workbook.close()


def test_sheet_names_are_sanitized_truncated_and_unique(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    long_name = "Extremely long sample identifier beyond thirty one characters"
    spectra = (
        _spectrum("a", "GaAs/300 K [PL]"),
        _spectrum("b", long_name),
        _spectrum("c", long_name),
        _spectrum("d", "Peaks"),
    )
    peaks = (_peak("a", "GaAs/300 K [PL]", 870.0, included=True),)

    target = tmp_path / "names.xlsx"
    SpectrumTableExporter().export(spectra, target, peak_records=peaks)

    workbook = openpyxl.load_workbook(target)
    try:
        sheet_names = workbook.sheetnames
        assert sheet_names == [
            "GaAs-300 K -PL-",
            f"{long_name[:31]}",
            f"{long_name[:27]} (2)",
            "Peaks (2)",
            "Peaks",
        ]
        for name in sheet_names:
            assert len(name) <= 31
            assert not set(name) & set("[]:*?/\\")
        assert len({name.casefold() for name in sheet_names}) == len(sheet_names)
        assert workbook["Peaks"].max_row == 2
        assert workbook["Peaks (2)"].max_row == 4
    finally:
        workbook.close()


def test_export_requires_a_checked_curve(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as error:
        SpectrumTableExporter().export((), tmp_path / "empty.xlsx")

    assert error.value.code == "E_EXPORT_NO_RESULTS"


def test_export_rejects_a_non_excel_target(tmp_path: Path) -> None:
    with pytest.raises(ExportError) as error:
        SpectrumTableExporter().export((_spectrum("one", "AGA017"),), tmp_path / "curves.csv")

    assert error.value.code == "E_EXPORT_FORMAT"


def test_export_does_not_leave_a_temporary_file_behind(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    target = tmp_path / "curves.xlsx"

    SpectrumTableExporter().export((_spectrum("one", "AGA017"),), target)

    assert [path.name for path in tmp_path.iterdir()] == ["curves.xlsx"]


def test_main_window_exports_only_the_checked_curves(
    qtbot: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Samples-list button must write exactly the checked curves."""

    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QFileDialog

    from analysis.raw_peak import RawPeakAnalyzer
    from core.configuration import ApplicationSettings, MaterialDatabase, application_root
    from core.importing.service import SpectrumImportService
    from core.workspace import Workspace
    from export.peak_table import PeakTableExporter
    from ui.main_window import MainWindow

    root = application_root()
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")
    workspace = Workspace(settings.plot)
    checked = _spectrum("one", "AGA017")
    unchecked = _spectrum("two", "AGA018")
    unchecked.display.visible = False
    workspace.add_spectra([checked, unchecked])
    window = MainWindow(
        workspace=workspace,
        importer=SpectrumImportService(),
        analyzer=RawPeakAnalyzer(),
        exporter=PeakTableExporter(),
        material_database=materials,
        analysis_defaults=settings.analysis,
    )
    qtbot.addWidget(window)
    target = tmp_path / "checked.xlsx"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(target), "Excel workbook (*.xlsx)")),
    )

    window._sample_panel._export_button.click()

    assert target.is_file()
    workbook = openpyxl.load_workbook(target)
    try:
        assert workbook.sheetnames == ["AGA017"]
        curve = workbook["AGA017"]
        assert curve.max_row == 4
        assert curve["A2"].value == pytest.approx(860.0)
        assert curve["B2"].value == pytest.approx(1.5)
    finally:
        workbook.close()
    window._set_dirty(False)
