"""File-format readers that expose a common tabular sheet representation."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Protocol

from core.errors import DataImportError


@dataclass(frozen=True, slots=True)
class TabularSheet:
    """Rows from one source sheet."""

    name: str | None
    rows: tuple[tuple[Any, ...], ...]
    display_name: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TabularSheetError:
    """A recoverable failure limited to one sheet inside a readable file."""

    name: str | None
    error: DataImportError


TabularReadResult = TabularSheet | TabularSheetError


class TabularReader(Protocol):
    """Structural protocol for registered readers."""

    def read(self, path: Path) -> tuple[TabularReadResult, ...]:
        """Read a file into one or more sheets."""


class CsvReader:
    """Read delimited text with UTF-8 and common Chinese encoding support."""

    _ENCODINGS = ("utf-8-sig", "gb18030", "utf-16")

    def read(self, path: Path) -> tuple[TabularSheet, ...]:
        text: str | None = None
        last_error: UnicodeError | None = None
        for encoding in self._ENCODINGS:
            try:
                text = path.read_text(encoding=encoding)
                break
            except UnicodeError as exc:
                last_error = exc
            except OSError as exc:
                raise DataImportError(
                    f"Unable to read CSV file: {path.name}",
                    code="E_IMPORT_FILE_READ",
                    detail=str(exc),
                ) from exc
        if text is None:
            raise DataImportError(
                f"Unable to decode CSV file: {path.name}",
                code="E_IMPORT_CSV_ENCODING",
                detail=str(last_error) if last_error else None,
            )

        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            rows = tuple(tuple(row) for row in csv.reader(text.splitlines(), dialect))
        except csv.Error:
            rows = tuple(tuple(row) for row in csv.reader(text.splitlines()))
        return (TabularSheet(name=None, rows=rows),)


class DatReader:
    """Read the three-column ASCII export produced by the PL spectrometer."""

    _ENCODINGS = ("utf-8-sig", "gb18030")
    _DATA_ROW = re.compile(
        r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*,\s*"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*,\s*"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*$"
    )

    def read(self, path: Path) -> tuple[TabularSheet, ...]:
        text = self._read_text(path)
        metadata: list[tuple[str, str]] = []
        corrected_rows: list[tuple[float, float]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            match = self._DATA_ROW.match(line)
            if match is not None:
                wavelength, signal, baseline = (float(value) for value in match.groups())
                corrected_rows.append((wavelength, signal - baseline))
                continue
            if ":" in line and not corrected_rows:
                key, value = line.split(":", 1)
                normalized_key = " ".join(key.split())
                if normalized_key:
                    metadata.append((normalized_key, value.strip()))

        if len(corrected_rows) < 3:
            raise DataImportError(
                f"No valid three-column PL spectrum was found in DAT file: {path.name}",
                code="E_IMPORT_DAT_STRUCTURE",
                detail="Expected Wavelength, Signal, Baseline rows with at least three points.",
            )

        rows: tuple[tuple[Any, ...], ...] = (
            ("Wavelength (nm)", "Corrected signal (mV)"),
            *corrected_rows,
        )
        metadata_tuple = tuple(metadata)
        return (
            TabularSheet(
                name=None,
                rows=rows,
                display_name=_dat_sample_name(path, metadata_tuple),
                metadata=metadata_tuple,
                diagnostics=("INSTRUMENT_BASELINE_SUBTRACTED",),
            ),
        )

    def _read_text(self, path: Path) -> str:
        last_error: UnicodeError | None = None
        for encoding in self._ENCODINGS:
            try:
                return path.read_text(encoding=encoding)
            except UnicodeError as exc:
                last_error = exc
            except OSError as exc:
                raise DataImportError(
                    f"Unable to read DAT file: {path.name}",
                    code="E_IMPORT_FILE_READ",
                    detail=str(exc),
                ) from exc
        raise DataImportError(
            f"Unable to decode DAT file: {path.name}",
            code="E_IMPORT_DAT_ENCODING",
            detail=str(last_error) if last_error else None,
        )


class XlsxReader:
    """Read modern Excel workbooks through openpyxl."""

    def read(self, path: Path) -> tuple[TabularSheet, ...]:
        try:
            from openpyxl import load_workbook
        except ImportError as exc:
            raise DataImportError(
                "XLSX support requires openpyxl.",
                code="E_IMPORT_DEPENDENCY",
                detail="Install dependencies from requirements.txt.",
            ) from exc

        try:
            workbook = load_workbook(path, read_only=True, data_only=True)
            sheets = tuple(
                TabularSheet(
                    name=worksheet.title,
                    rows=tuple(tuple(row) for row in worksheet.iter_rows(values_only=True)),
                )
                for worksheet in workbook.worksheets
            )
            workbook.close()
            return sheets
        except Exception as exc:
            raise DataImportError(
                f"Unable to read Excel workbook: {path.name}",
                code="E_IMPORT_XLSX_READ",
                detail=str(exc),
            ) from exc


class XlsReader:
    """Read legacy binary Excel workbooks through xlrd."""

    def read(self, path: Path) -> tuple[TabularSheet, ...]:
        try:
            import xlrd
        except ImportError as exc:
            raise DataImportError(
                "Legacy XLS support requires xlrd.",
                code="E_IMPORT_DEPENDENCY",
                detail="Install dependencies from requirements.txt.",
            ) from exc

        try:
            workbook = xlrd.open_workbook(str(path), on_demand=True)
            sheets: list[TabularSheet] = []
            for sheet_name in workbook.sheet_names():
                worksheet = workbook.sheet_by_name(sheet_name)
                rows = tuple(
                    tuple(worksheet.cell_value(row, column) for column in range(worksheet.ncols))
                    for row in range(worksheet.nrows)
                )
                sheets.append(TabularSheet(name=sheet_name, rows=rows))
            workbook.release_resources()
            return tuple(sheets)
        except Exception as exc:
            raise DataImportError(
                f"Unable to read legacy Excel workbook: {path.name}",
                code="E_IMPORT_XLS_READ",
                detail=str(exc),
            ) from exc


class ReaderRegistry:
    """Map supported extensions to isolated reader implementations."""

    def __init__(self, origin_reader: TabularReader | None = None) -> None:
        if origin_reader is None:
            from .origin_reader import OriginProjectReader

            origin_reader = OriginProjectReader()
        self._readers: dict[str, TabularReader] = {
            ".dat": DatReader(),
            ".csv": CsvReader(),
            ".xlsx": XlsxReader(),
            ".xlsm": XlsxReader(),
            ".xls": XlsReader(),
            ".opj": origin_reader,
            ".opju": origin_reader,
        }

    @property
    def supported_extensions(self) -> frozenset[str]:
        """Return recognized lowercase file extensions."""

        return frozenset(self._readers)

    def read(self, path: Path) -> tuple[TabularReadResult, ...]:
        """Dispatch a source file to its registered reader."""

        if not path.exists() or not path.is_file():
            raise DataImportError(
                f"File does not exist: {path}",
                code="E_IMPORT_FILE_NOT_FOUND",
            )
        reader = self._readers.get(path.suffix.casefold())
        if reader is None:
            raise DataImportError(
                f"Unsupported file type: {path.suffix or '(none)'}",
                code="E_IMPORT_UNSUPPORTED_FORMAT",
            )
        return reader.read(path)


def _dat_sample_name(path: Path, metadata: tuple[tuple[str, str], ...]) -> str:
    values = {key.strip().casefold(): value.strip() for key, value in metadata}
    folder = values.get("folder", "")
    if folder:
        candidate = PureWindowsPath(folder).name or Path(folder).name
        if candidate:
            return _clean_sample_name(candidate)
    filename = values.get("filename", "")
    if filename:
        return _clean_sample_name(Path(filename).stem)
    return _clean_sample_name(path.stem)


def _clean_sample_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "-", value.strip()).strip("-_.")
    if not cleaned:
        return "PL-sample"
    return cleaned.upper() if cleaned.casefold().startswith("qw-") else cleaned
