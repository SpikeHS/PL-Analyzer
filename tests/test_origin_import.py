"""Origin project adapter, routing, and recovery tests."""

from __future__ import annotations

import ast
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from core.errors import DataImportError
from core.importing._origin_parser import read_origin_books
from core.importing.origin_backend import (
    BundledOriginBackend,
    OriginColumn,
    OriginWorksheet,
)
from core.importing.origin_reader import OriginProjectReader
from core.importing.readers import ReaderRegistry
from core.importing.service import SpectrumImportService

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGIN_PARSER_ROOT = PROJECT_ROOT / "core" / "importing" / "_origin_parser"
ORIGIN_UPSTREAM_COMMIT = "c34980b82947af3f82f7a9a4ff5692610ba5398f"


class FakeOriginBackend:
    """Deterministic backend used to exercise the application adapter."""

    def __init__(self, worksheets: tuple[OriginWorksheet, ...]) -> None:
        self.worksheets = worksheets
        self.calls: list[Path] = []

    def read_project(self, path: Path) -> tuple[OriginWorksheet, ...]:
        self.calls.append(path)
        return self.worksheets


def _origin_block(payload: bytes) -> bytes:
    """Build one length-delimited CPYA record for the parser regression fixture."""

    return struct.pack("<I", len(payload)) + b"\n" + payload + b"\n"


def _origin_column_header(name: str) -> bytes:
    payload = b"\x00" * 40 + name.encode("latin1") + b"\x00" + b"\x00" * 6
    if len(payload) % 10 == 0:
        payload += b"\x00"
    return _origin_block(payload)


def _origin_numeric_column(values: tuple[float, ...]) -> bytes:
    payload = b"".join(b"\x00\x00" + struct.pack("<d", value) for value in values)
    return _origin_block(payload)


def _synthetic_opj() -> bytes:
    """Return a minimal, redistributable CPYA workbook with X and Y columns."""

    spacer = struct.pack("<I", 0) + b"\n"
    return (
        b"CPYA 4.3380 188 W64 #\n"
        + _origin_block(b"\x00" * 32)
        + spacer
        + _origin_column_header("Book1_A")
        + _origin_numeric_column((860.0, 870.0, 880.0))
        + spacer
        + _origin_column_header("Book1_B")
        + _origin_numeric_column((1.0, 4.0, 1.0))
    )


def _pl_worksheet(name: str = "Book1") -> OriginWorksheet:
    wavelengths = (749.4, 749.6, 749.9, 750.2)
    return OriginWorksheet(
        name=name,
        columns=(
            OriginColumn("A", "Wavelength", "[nm]", "X", wavelengths),
            OriginColumn("B", "Signal", "[mV]", "Y", (0.010, 0.009, 0.008, 0.007)),
            OriginColumn("C", "Baseline", "[mV]", "Y", (0.0, 0.0, 0.0, 0.0)),
        ),
    )


def test_origin_reader_preserves_complete_worksheet_and_units(tmp_path: Path) -> None:
    source = tmp_path / "instrument.opju"
    source.write_bytes(b"CPYUA " + b"fixture")
    backend = FakeOriginBackend((_pl_worksheet("Folder / VN2696"),))

    sheets = OriginProjectReader(backend).read(source)

    assert backend.calls == [source]
    assert len(sheets) == 1
    assert sheets[0].name == "Folder / VN2696"
    assert sheets[0].rows[0] == (
        "Wavelength [nm]",
        "Signal [mV]",
        "Baseline [mV]",
    )
    assert sheets[0].rows[1] == (749.4, 0.010, 0.0)


def test_import_selects_signal_without_treating_baseline_as_sample(tmp_path: Path) -> None:
    source = tmp_path / "PL DATA.opju"
    source.write_bytes(b"CPYUA " + b"fixture")
    reader = OriginProjectReader(FakeOriginBackend((_pl_worksheet("VN2696"),)))
    service = SpectrumImportService(registry=ReaderRegistry(origin_reader=reader))

    report = service.import_paths([source])

    assert not report.issues
    assert len(report.spectra) == 1
    assert report.spectra[0].name == "PL DATA"
    assert report.spectra[0].source.sheet_name == "VN2696"
    assert report.spectra[0].source.wavelength_column == "Wavelength [nm]"
    assert report.spectra[0].source.intensity_column == "Signal [mV]"
    np.testing.assert_allclose(report.spectra[0].intensity_au, [0.010, 0.009, 0.008, 0.007])


def test_multiple_origin_books_become_multiple_spectra(tmp_path: Path) -> None:
    source = tmp_path / "multi.opj"
    source.write_bytes(b"CPYA " + b"fixture")
    reader = OriginProjectReader(
        FakeOriginBackend(
            (
                _pl_worksheet("Book A"),
                _pl_worksheet("Book B"),
            )
        )
    )
    service = SpectrumImportService(registry=ReaderRegistry(origin_reader=reader))

    report = service.import_paths([source])

    assert not report.issues
    assert [spectrum.name for spectrum in report.spectra] == [
        "multi / Book A",
        "multi / Book B",
    ]


def test_wrong_opj_signature_is_recoverable_and_backend_is_not_called(
    tmp_path: Path,
) -> None:
    source = tmp_path / "orcad.opj"
    source.write_bytes(b"(ExpressProject")
    backend = FakeOriginBackend((_pl_worksheet(),))

    report = SpectrumImportService(
        registry=ReaderRegistry(origin_reader=OriginProjectReader(backend))
    ).import_paths([source])

    assert not report.spectra
    assert len(report.issues) == 1
    assert report.issues[0].code == "E_IMPORT_ORIGIN_SIGNATURE"
    assert not backend.calls


def test_truncated_origin_project_is_a_recoverable_parser_error(tmp_path: Path) -> None:
    source = tmp_path / "truncated.opju"
    source.write_bytes(b"CPYUA 4.3668 170\n")

    report = SpectrumImportService().import_paths([source])

    assert not report.spectra
    assert len(report.issues) == 1
    assert report.issues[0].code == "E_IMPORT_ORIGIN_READ"
    assert "no worksheet columns" in (report.issues[0].detail or "")


def test_unrecovered_origin_x_is_not_silently_used_as_wavelength(
    tmp_path: Path,
) -> None:
    source = tmp_path / "partial.opju"
    source.write_bytes(b"CPYUA " + b"fixture")
    invalid = OriginWorksheet(
        name="Missing X",
        columns=_pl_worksheet().columns,
        x_column_recovered=False,
    )
    reader = OriginProjectReader(
        FakeOriginBackend(
            (
                invalid,
                _pl_worksheet("Valid PL"),
            )
        )
    )

    report = SpectrumImportService(registry=ReaderRegistry(origin_reader=reader)).import_paths(
        [source]
    )

    assert len(report.spectra) == 1
    assert report.spectra[0].source.sheet_name == "Valid PL"
    assert len(report.issues) == 1
    assert report.issues[0].source.endswith("[Missing X]")
    assert report.issues[0].code == "E_IMPORT_ORIGIN_X_COLUMN"
    assert "synthetic row index" in (report.issues[0].detail or "")


def test_bad_origin_project_does_not_abort_csv_in_same_batch(tmp_path: Path) -> None:
    broken = tmp_path / "broken.opju"
    broken.write_bytes(b"not an Origin project")
    valid = tmp_path / "valid.csv"
    valid.write_text("Wavelength,Intensity\n860,1\n870,4\n880,1\n", encoding="utf-8")

    report = SpectrumImportService().import_paths([broken, valid])

    assert len(report.spectra) == 1
    assert report.spectra[0].name == "valid"
    assert len(report.issues) == 1
    assert report.issues[0].code == "E_IMPORT_ORIGIN_SIGNATURE"


def test_bundled_backend_maps_parser_metadata_without_leaking_parser_types(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mapped.opju"
    book = SimpleNamespace(
        time=np.asarray([750.0, 751.0, 752.0]),
        values=np.asarray([[1.0, 0.0], [2.0, 0.0], [1.0, 0.0]]),
        labels=("Signal", "Baseline"),
        units=("[mV]", "[mV]"),
        metadata={
            "origin_book": "Book1",
            "origin_book_long": "VN2696",
            "origin_folder_path": ["PL", "300 K"],
            "x_column_name": "A",
            "x_column_long": "Wavelength",
            "x_column_unit": "[nm]",
            "origin_column_names": ["B", "C"],
            "column_designations": {"A": "X", "B": "Y", "C": "Y"},
            "x_column_recovered": True,
        },
    )

    worksheets = BundledOriginBackend(loader=lambda _path: [book]).read_project(source)

    assert len(worksheets) == 1
    assert worksheets[0].name == "PL / 300 K / VN2696 [Book1]"
    assert [column.short_name for column in worksheets[0].columns] == ["A", "B", "C"]
    assert [column.designation for column in worksheets[0].columns] == ["X", "Y", "Y"]
    assert worksheets[0].columns[0].values == (750.0, 751.0, 752.0)
    assert worksheets[0].x_column_recovered is True


@pytest.mark.parametrize(
    ("short_name", "label", "designations"),
    [
        ("time", "Time", {}),
        ("Fit", "Fit", {"Fit": "X"}),
    ],
)
def test_bundled_backend_rejects_ambiguous_assumed_x_axes(
    tmp_path: Path,
    short_name: str,
    label: str,
    designations: dict[str, str],
) -> None:
    book = SimpleNamespace(
        time=np.asarray([1.0, 2.0, 3.0]),
        values=np.asarray([[1.0], [2.0], [1.0]]),
        labels=("Signal",),
        units=("[mV]",),
        metadata={
            "origin_book": "Data1",
            "origin_book_long": "BA",
            "x_column_name": short_name,
            "x_column_long": label,
            "x_column_unit": "",
            "origin_column_names": ["B"],
            "column_designations": designations,
            "x_column_recovered": True,
        },
    )

    worksheet = BundledOriginBackend(loader=lambda _path: [book]).read_project(
        tmp_path / "ambiguous.opj"
    )[0]

    assert worksheet.name == "BA [Data1]"
    assert worksheet.columns[0].designation == designations.get(short_name)
    assert worksheet.x_column_recovered is False


@pytest.mark.parametrize(
    ("short_name", "label", "unit"),
    [
        ("A", "Wavelength", ""),
        ("A", "波长", ""),
        ("λ", "λ", ""),
        ("A", "A", "[nm]"),
    ],
)
def test_bundled_backend_accepts_strong_wavelength_semantics_without_designation(
    tmp_path: Path,
    short_name: str,
    label: str,
    unit: str,
) -> None:
    book = SimpleNamespace(
        time=np.asarray([860.0, 870.0, 880.0]),
        values=np.asarray([[1.0], [4.0], [1.0]]),
        labels=("Signal",),
        units=("[mV]",),
        metadata={
            "origin_book": "Book1",
            "x_column_name": short_name,
            "x_column_long": label,
            "x_column_unit": unit,
            "origin_column_names": ["B"],
            "column_designations": {},
            "x_column_recovered": True,
        },
    )

    worksheet = BundledOriginBackend(loader=lambda _path: [book]).read_project(
        tmp_path / "semantic.opj"
    )[0]

    assert worksheet.columns[0].designation is None
    assert worksheet.x_column_recovered is True


def test_bundled_backend_preserves_explicit_x_for_generic_column_name(
    tmp_path: Path,
) -> None:
    book = SimpleNamespace(
        time=np.asarray([860.0, 870.0, 880.0]),
        values=np.asarray([[1.0], [4.0], [1.0]]),
        labels=("B",),
        units=("",),
        metadata={
            "origin_book": "Book1",
            "x_column_name": "A",
            "x_column_long": "A",
            "x_column_unit": "",
            "origin_column_names": ["B"],
            "column_designations": {"A": "X", "B": "Y"},
            "x_column_recovered": True,
        },
    )

    worksheet = BundledOriginBackend(loader=lambda _path: [book]).read_project(
        tmp_path / "designated.opj"
    )[0]

    assert worksheet.columns[0].designation == "X"
    assert worksheet.x_column_recovered is True


def test_bundled_backend_never_overrides_parser_unrecovered_axis(
    tmp_path: Path,
) -> None:
    book = SimpleNamespace(
        time=np.asarray([0.0, 1.0, 2.0]),
        values=np.asarray([[860.0, 1.0], [870.0, 4.0], [880.0, 1.0]]),
        labels=("Wavelength", "Signal"),
        units=("[nm]", "[mV]"),
        metadata={
            "origin_book": "Book1",
            "x_column_name": "",
            "x_column_long": "Row",
            "x_column_unit": "",
            "origin_column_names": ["A", "B"],
            "column_designations": {"A": "X", "B": "Y"},
            "x_column_recovered": False,
        },
    )

    worksheet = BundledOriginBackend(loader=lambda _path: [book]).read_project(
        tmp_path / "unrecovered.opj"
    )[0]

    assert worksheet.x_column_recovered is False


def test_bundled_backend_contains_parser_failures(tmp_path: Path) -> None:
    def fail(_path: Path) -> list[object]:
        raise ValueError("truncated CPYUA record")

    with pytest.raises(DataImportError) as caught:
        BundledOriginBackend(loader=fail).read_project(tmp_path / "bad.opju")

    assert caught.value.code == "E_IMPORT_ORIGIN_READ"
    assert caught.value.detail == "truncated CPYUA record"


def test_default_registry_advertises_both_origin_extensions() -> None:
    extensions = ReaderRegistry().supported_extensions

    assert ".opj" in extensions
    assert ".opju" in extensions


def test_vendored_parser_decodes_synthetic_legacy_opj(tmp_path: Path) -> None:
    source = tmp_path / "legacy.OPJ"
    source.write_bytes(_synthetic_opj())

    books = read_origin_books(source)

    assert len(books) == 1
    np.testing.assert_allclose(books[0].time, [860.0, 870.0, 880.0])
    np.testing.assert_allclose(books[0].values[:, 0], [1.0, 4.0, 1.0])
    assert books[0].labels == ("B",)
    assert books[0].metadata["origin_book"] == "Book1"
    assert books[0].metadata["column_designations"] == {}

    report = SpectrumImportService().import_paths([source])

    assert not report.spectra
    assert [issue.code for issue in report.issues] == ["E_IMPORT_ORIGIN_X_COLUMN"]


def test_vendored_origin_parser_has_no_unapproved_runtime_dependencies() -> None:
    allowed_external_imports = {"numpy"}
    unexpected_imports: set[str] = set()

    for source_path in ORIGIN_PARSER_ROOT.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates = (alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                candidates = (node.module.split(".", 1)[0],)
            else:
                continue
            unexpected_imports.update(
                name
                for name in candidates
                if name not in sys.stdlib_module_names and name not in allowed_external_imports
            )

    assert not unexpected_imports


def test_origin_parser_provenance_and_notices_are_release_assets() -> None:
    upstream = (ORIGIN_PARSER_ROOT / "UPSTREAM.md").read_text(encoding="utf-8")
    license_text = (ORIGIN_PARSER_ROOT / "LICENSE").read_text(encoding="utf-8")
    notice = (ORIGIN_PARSER_ROOT / "NOTICE").read_text(encoding="utf-8")
    spec = (PROJECT_ROOT / "PLAnalyzerPro.spec").read_text(encoding="utf-8")

    assert ORIGIN_UPSTREAM_COMMIT in upstream
    assert "Apache License" in license_text
    assert "Copyright 2026 Paige Quarterman" in notice
    assert '"licenses/quantized-origin"' in spec
    assert '("LICENSE", "NOTICE", "UPSTREAM.md")' in spec
