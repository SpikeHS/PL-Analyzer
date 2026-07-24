# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro only to use the local relative import namespace.
# ruff: noqa: I001
"""Read Origin ``.opju`` (CPYUA, 2018+) projects: worksheet data → DataStruct.

The worksheet-column codec is solved (``opju_codec.py``): each column is an
FPC-compressed float64 stream, located by its LEB128-varint record header and
labelled by the nearest preceding ``<Book>_<Col>[@sheet]`` dataset name. Books
are grouped and assembled exactly like the ``.opj`` reader (shared ``_group``
/ ``_build_book`` / ``_inventory``). Column long-names/units/comments come
from the CPYUA windows section (``windows_opju.py``, plan item 10) the same
way `.opj`'s windows-section metadata feeds ``_build_book`` — designation-X
becomes the x axis, real labels/units/comments attach where a book's window
section can be structurally confirmed, and book display titles recover from
the embedded import filename where available. Columns/books that can't be
confirmed keep the Origin short-designation fallback (A, B, C…) rather than
being guessed at.

Plan item 4's report-sheet residue (``opju_reports.py``) is folded in the
same way ``.opj``'s ``text_cols``/``report_cols`` are: a book made entirely
of report-sheet columns (e.g. a fit's "FitNL1" sheet, with zero
plausible-numeric columns of its own) still gets its own pseudo-book via
``_build_book``'s empty-``cols`` branch, rather than being silently dropped
for having nothing in ``books``.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from .datastruct import DataStruct
from .container import fallback
from .opj import (
    Columns,
    TextColumns,
    _build_book,
    _group,
    _group_named,
    _inventory,
)
from .opju_codec import scan_columns
from .opju_reports import scan_report_columns
from .windows import BookMeta
from .windows_opju import opju_window_metadata

__all__ = [
    "build_opju_books",
    "build_opju_primary",
    "parse_opju",
    "read_opju",
    "read_opju_books",
]

_ParseResult = tuple[
    OrderedDict[str, Columns],
    OrderedDict[str, TextColumns],
    dict[str, BookMeta],
    list[dict[str, object]],
]


def _parse(path: Path, *, raw: bytes | None = None) -> _ParseResult:
    """Decode the project once. ``raw`` lets a caller that already has the
    file's bytes (e.g. :func:`parse_opju`'s callers in
    ``origin_project/__init__.py``) skip a second disk read; ``None`` (the
    default) reads ``path`` itself, unchanged from before."""
    b = path.read_bytes() if raw is None else raw
    if not b.startswith(b"CPYUA"):
        raise fallback(path, f"'{path.name}' does not look like a CPYUA .opju (bad header).")
    columns = scan_columns(b)
    if not columns:
        raise fallback(path, f"no worksheet columns could be decoded from '{path.name}'.")
    books = _group(columns)
    report_books = _group_named(scan_report_columns(b))
    books_meta = opju_window_metadata(b, {k: [c for c, _ in v] for k, v in books.items()})
    return books, report_books, books_meta, _inventory(books, books_meta, report_books)


def _primary_key(books: OrderedDict[str, Columns]) -> str:
    """The book :func:`read_opju`/:func:`build_opju_primary` treat as *the*
    primary dataset — see ``opj._primary_key`` (identical selection rule,
    duplicated here since the two containers' ``Columns`` groupings are
    built independently)."""
    primary_pool = [k for k in books if "@" not in k] or list(books)
    return max(primary_pool, key=lambda k: sum(len(v) for _, v in books[k]))


def parse_opju(path: Path, *, raw: bytes | None = None) -> _ParseResult:
    """Public single-parse entry point — see ``opj.parse_opj``. Lets a caller
    that needs both the primary book (:func:`build_opju_primary`) and every
    book (:func:`build_opju_books`) parse the project once."""
    return _parse(path, raw=raw)


def build_opju_primary(parsed: _ParseResult) -> DataStruct:
    """Build the primary book's DataStruct from an already-:func:`parse_opju`'d
    project — see ``opj.build_opj_primary``."""
    books, report_books, books_meta, inventory = parsed
    primary = _primary_key(books)
    return _build_book(
        primary,
        books[primary],
        books_meta,
        inventory,
        source_format="origin_opju",
        report_cols=report_books.get(primary),
    )


def build_opju_books(parsed: _ParseResult) -> list[DataStruct]:
    """Build every book's DataStruct from an already-:func:`parse_opju`'d
    project — see ``opj.build_opj_books``.

    A sheet made entirely of report-sheet columns (plan item 4) has no
    plausible-numeric columns, so it never appears in ``books`` — the union
    with ``report_books`` below still surfaces it as its own pseudo-book
    (see ``_build_book``'s empty-``cols`` branch).
    """
    books, report_books, books_meta, inventory = parsed
    keys = list(books) + [k for k in report_books if k not in books]
    return [
        _build_book(
            k,
            books.get(k, []),
            books_meta,
            inventory,
            source_format="origin_opju",
            report_cols=report_books.get(k),
        )
        for k in keys
        if books.get(k) or report_books.get(k)
    ]


def read_opju(path: Path) -> DataStruct:
    """The single-DataStruct contract: the largest workbook (inventory in metadata)."""
    return build_opju_primary(_parse(path))


def read_opju_books(path: Path) -> list[DataStruct]:
    """Every workbook in the project as its own DataStruct (plan item 3/16).

    A sheet made entirely of report-sheet columns (plan item 4) has no
    plausible-numeric columns, so it never appears in ``books`` — the union
    with ``report_books`` below still surfaces it as its own pseudo-book
    (see ``_build_book``'s empty-``cols`` branch).
    """
    return build_opju_books(_parse(path))
