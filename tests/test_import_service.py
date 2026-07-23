"""CSV, XLSX, XLS adapter and batch recovery tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.importing.readers import XlsReader
from core.importing.service import SpectrumImportService


def test_imports_gb18030_csv_with_automatic_columns(tmp_path: Path) -> None:
    source = tmp_path / "AGA017.csv"
    source.write_text(
        "波长 (nm),强度 (a.u.)\n860,1\n870,5\n880,2\n",
        encoding="gb18030",
    )

    report = SpectrumImportService().import_paths([source])

    assert not report.issues
    assert len(report.spectra) == 1
    assert report.spectra[0].name == "AGA017"
    assert report.spectra[0].source.wavelength_column == "波长 (nm)"


def test_imports_each_compatible_xlsx_sheet_and_reports_bad_sheet(
    tmp_path: Path,
) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    source = tmp_path / "AGA030.xlsx"
    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "300K"
    first.append(["Wavelength (nm)", "Intensity (counts)"])
    for row in ((860, 1), (870, 3), (880, 1)):
        first.append(row)
    second = workbook.create_sheet("77K")
    second.append(["Wavelength", "PL"])
    for row in ((850, 2), (860, 8), (870, 2)):
        second.append(row)
    notes = workbook.create_sheet("Notes")
    notes.append(["operator", "comment"])
    workbook.save(source)

    report = SpectrumImportService().import_paths([source])

    assert [spectrum.name for spectrum in report.spectra] == [
        "AGA030 / 300K",
        "AGA030 / 77K",
    ]
    assert len(report.issues) == 1
    assert report.issues[0].source.endswith("[Notes]")


def test_bad_file_does_not_abort_valid_file(tmp_path: Path) -> None:
    valid = tmp_path / "valid.csv"
    valid.write_text("nm,intensity\n1,1\n2,4\n3,1\n", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_text("not supported", encoding="utf-8")

    report = SpectrumImportService().import_paths([bad, valid])

    assert len(report.spectra) == 1
    assert len(report.issues) == 1
    assert report.issues[0].code == "E_IMPORT_UNSUPPORTED_FORMAT"


def test_xls_reader_uses_isolated_xlrd_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "legacy.xls"
    source.write_bytes(b"test fixture placeholder")

    class FakeSheet:
        nrows = 4
        ncols = 2

        @staticmethod
        def cell_value(row: int, column: int) -> object:
            values = [
                ["Wavelength", "Intensity"],
                [860.0, 1.0],
                [870.0, 4.0],
                [880.0, 1.0],
            ]
            return values[row][column]

    class FakeWorkbook:
        @staticmethod
        def sheet_names() -> list[str]:
            return ["Sheet1"]

        @staticmethod
        def sheet_by_name(_name: str) -> FakeSheet:
            return FakeSheet()

        @staticmethod
        def release_resources() -> None:
            return None

    fake_xlrd = SimpleNamespace(open_workbook=lambda *_args, **_kwargs: FakeWorkbook())
    monkeypatch.setitem(sys.modules, "xlrd", fake_xlrd)

    sheets = XlsReader().read(source)

    assert len(sheets) == 1
    assert sheets[0].name == "Sheet1"
    assert sheets[0].rows[1] == (860.0, 1.0)
