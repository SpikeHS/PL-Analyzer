"""Origin project backend contracts and the bundled parser adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from core.errors import DataImportError


@dataclass(frozen=True, slots=True)
class OriginColumn:
    """One numeric Origin worksheet column with its scientific metadata."""

    short_name: str
    label: str
    unit: str
    designation: str | None
    values: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class OriginWorksheet:
    """One workbook sheet normalized for the tabular import layer."""

    name: str
    columns: tuple[OriginColumn, ...]
    x_column_recovered: bool = True


class OriginProjectBackend(Protocol):
    """Structural interface implemented by an Origin project parser."""

    def read_project(self, path: Path) -> tuple[OriginWorksheet, ...]:
        """Read every worksheet-like book in an Origin project."""


OriginBooksLoader = Callable[[Path], Sequence[Any]]


class BundledOriginBackend:
    """Adapt the bundled clean-room OPJ/OPJU reader to import-layer models."""

    def __init__(self, loader: OriginBooksLoader | None = None) -> None:
        self._loader = loader

    def read_project(self, path: Path) -> tuple[OriginWorksheet, ...]:
        """Decode worksheet books while containing all parser exceptions."""

        loader = self._loader
        if loader is None:
            try:
                from ._origin_parser import read_origin_books
            except ImportError as exc:
                raise DataImportError(
                    "The bundled Origin project reader is unavailable.",
                    code="E_IMPORT_ORIGIN_COMPONENT",
                    detail="Reinstall PL Analyzer Pro from an official release package.",
                ) from exc
            loader = read_origin_books

        try:
            books = loader(path)
            return tuple(
                worksheet
                for index, book in enumerate(books)
                if (worksheet := _convert_book(book, fallback_name=f"Book {index + 1}")) is not None
            )
        except DataImportError:
            raise
        except Exception as exc:
            raise DataImportError(
                f"Unable to read Origin project: {path.name}",
                code="E_IMPORT_ORIGIN_READ",
                detail=str(exc),
            ) from exc


def _convert_book(book: Any, *, fallback_name: str) -> OriginWorksheet | None:
    """Convert the parser's immutable DataStruct without leaking that type."""

    metadata = _metadata(book)
    time = np.asarray(book.time, dtype=np.float64).reshape(-1)
    values = np.asarray(book.values, dtype=np.float64)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    if values.ndim != 2:
        raise ValueError(f"Origin worksheet values must be 2-D, got {values.ndim}-D.")
    if values.shape[0] != time.size:
        raise ValueError(
            f"Origin worksheet X/Y row counts differ: {time.size} versus {values.shape[0]}."
        )

    labels = tuple(str(value) for value in getattr(book, "labels", ()))
    units = tuple(str(value) for value in getattr(book, "units", ()))
    if len(labels) != values.shape[1] or len(units) != values.shape[1]:
        raise ValueError("Origin worksheet column metadata does not match its data shape.")

    short_names = _string_sequence(metadata.get("origin_column_names"))
    designations = _string_mapping(metadata.get("column_designations"))
    x_short_name = _text(metadata.get("x_column_name"), "X")
    x_label = _text(metadata.get("x_column_long"), x_short_name)
    x_unit = _text(
        metadata.get("x_column_unit"),
        _text(metadata.get("x_unit"), ""),
    )
    columns = [
        OriginColumn(
            short_name=x_short_name,
            label=x_label,
            unit=x_unit,
            designation=designations.get(x_short_name, "X"),
            values=tuple(float(value) for value in time),
        )
    ]
    for index in range(values.shape[1]):
        short_name = (
            short_names[index] if index < len(short_names) else _spreadsheet_column_name(index + 1)
        )
        columns.append(
            OriginColumn(
                short_name=short_name,
                label=labels[index] or short_name,
                unit=units[index],
                designation=designations.get(short_name),
                values=tuple(float(value) for value in values[:, index]),
            )
        )

    if len(columns) < 2:
        return None
    return OriginWorksheet(
        name=_worksheet_name(metadata, fallback_name),
        columns=tuple(columns),
        x_column_recovered=bool(metadata.get("x_column_recovered", True)),
    )


def _metadata(book: Any) -> Mapping[str, Any]:
    value = getattr(book, "metadata", {})
    return value if isinstance(value, Mapping) else {}


def _worksheet_name(metadata: Mapping[str, Any], fallback: str) -> str:
    folder = _string_sequence(metadata.get("origin_folder_path"))
    book_name = _text(
        metadata.get("origin_book_long"),
        _text(metadata.get("origin_book"), fallback),
    )
    return " / ".join((*folder, book_name)) if folder else book_name


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): str(item) for key, item in value.items() if str(key).strip() and str(item).strip()
    }


def _text(value: Any, fallback: str) -> str:
    text = str(value).strip() if value is not None else ""
    return text or fallback


def _spreadsheet_column_name(index: int) -> str:
    """Return Excel-style names so missing metadata remains traceable."""

    name = ""
    remaining = index
    while remaining:
        remaining, remainder = divmod(remaining - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name
