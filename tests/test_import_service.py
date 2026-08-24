"""CSV, XLSX, XLS adapter and batch recovery tests."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.errors import DataImportError
from core.importing.readers import DatReader, ReaderRegistry, XlsReader
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


def test_imports_instrument_dat_with_baseline_correction_and_metadata(
    tmp_path: Path,
) -> None:
    source = tmp_path / "instrument-export.dat"
    source.write_text(
        "\n".join(
            (
                "ASCII",
                r"Folder : d:\iii-v pl\2026\qw\qw-12",
                "Laser : 532.0 nm",
                "Power : 45.0 mW",
                "Wavelength, Signal, Baseline",
                "[nm], [mV], [mV]",
                "760.0, 1.25, 0.25",
                "761.0, 4.50, 0.50",
                "762.0, 2.75, 0.25",
            )
        ),
        encoding="ascii",
    )

    report = SpectrumImportService().import_paths([source])

    assert not report.issues
    assert len(report.spectra) == 1
    spectrum = report.spectra[0]
    assert spectrum.name == "QW-12"
    assert spectrum.intensity_au.tolist() == [1.0, 4.0, 2.5]
    assert spectrum.source.wavelength_column == "Wavelength (nm)"
    assert spectrum.source.intensity_column == "Corrected signal (mV)"
    assert spectrum.source.metadata_value("laser") == "532.0 nm"
    assert spectrum.source.metadata_value("POWER") == "45.0 mW"
    assert "INSTRUMENT_BASELINE_SUBTRACTED" in spectrum.diagnostics


def test_dat_reader_rejects_non_spectrometer_dat(tmp_path: Path) -> None:
    source = tmp_path / "invalid.dat"
    source.write_text("unrelated application data", encoding="utf-8")

    with pytest.raises(DataImportError) as caught:
        DatReader().read(source)

    assert getattr(caught.value, "code", None) == "E_IMPORT_DAT_STRUCTURE"


def test_default_registry_advertises_dat() -> None:
    assert ".dat" in ReaderRegistry().supported_extensions


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
