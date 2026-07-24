# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro only to use the local relative import namespace.
# ruff: noqa: I001, UP047
"""Read Origin ``.opj`` (CPYA) projects: worksheet data + column names/units.

M1 recovered the numeric columns (datasets named ``"<Book>_<Col>"``, 10-byte
``<mask><float64>`` records); this adds the windows-section metadata (plan
item 2): real column long names, units, comments, and X/Y designations. The
largest book returns as the :class:`~quantized.datastruct.DataStruct` (every
book's inventory stays in metadata; per-book selection is plan item 3/16).

Plan item 4 (non-double column value types) adds inline-text column decode:
a "Text & Numeric" column reuses the same 10-byte record as a double column,
but its 8-byte value area holds a short NUL-terminated string instead of a
raw float64 (`container.decode_inline_text`). Decoded text columns never
enter `.values` (the data contract is numeric); they attach to metadata as
`origin_text_columns: {short_name: [str, ...]}`. A column that overflows
`decode_inline_text`'s 8-byte value area (Origin's FitLinear/NLFit
auto-generated report-sheet columns, e.g. `"cell://Parameters.Slope.Value"`)
gets a second try via `container.decode_report_strings` — a wider,
column-specific record width — attaching to
`origin_report_sheets: {short_name: [str, ...]}`. Whatever fits neither
shape keeps the honest drop.

Column long names/units/comments and book display titles are Origin
LabTalk *label* fields — the exact same rich-text escape syntax as graph
axis titles (`figures.py`/`origin_richtext.py`), since Origin lets a user
type ``\\+(...)``/``\\g(...)``/etc. into a column's Long Name or Unit row
just as freely as into an axis title. Confirmed live in the corpus
(`MnN_Diffusion_PNR.opj`'s "Nuclear SLD" books carry a Unit of
``10\\+(-6) A\\+(-2)``): every such field is decoded through
`clean_richtext` here, at the one `_build_book` shared by both `.opj`
and `.opju` (`opju.py` reuses it verbatim) — the single chokepoint that
also feeds every frontend consumer of `.labels`/`.units`/
`x_column_unit`/`origin_book_long` (axis labels, per-series legends,
the worksheet header, the Inspector).
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import TypeVar

import numpy as np
from numpy.typing import NDArray

from .datastruct import DataStruct
from .container import (
    NAME_RE,
    decode_doubles,
    decode_inline_text,
    decode_report_strings,
    fallback,
    plausible_column,
    salvage_column,
    walk_blocks,
)
from .origin_richtext import clean_richtext
from .windows import BookMeta, ColumnMeta, window_metadata

__all__ = [
    "build_opj_books",
    "build_opj_primary",
    "parse_opj",
    "read_opj",
    "read_opj_books",
]

_V = TypeVar("_V")


def _columns(
    b: bytes,
) -> tuple[
    list[tuple[str, NDArray[np.float64]]], list[tuple[str, list[str]]], list[tuple[str, list[str]]]
]:
    """Walk the datasets section, pairing each named header block with its data.

    Returns ``(numeric_columns, text_columns, report_columns)``. A data block
    that isn't a plausible double column (see `plausible_column`/
    `_looks_textual`) is tried as short inline text (`decode_inline_text`),
    then — if that overflows — as a wider report-sheet record
    (`decode_report_strings`, plan item 4's FitLinear/NLFit residue);
    anything matching none of the three shapes is dropped exactly as before
    (honest-absent, never garbage).
    """
    numeric: list[tuple[str, NDArray[np.float64]]] = []
    text: list[tuple[str, list[str]]] = []
    report: list[tuple[str, list[str]]] = []
    pending: str | None = None
    for size, payload in walk_blocks(b):
        if size == 0:
            continue
        if size % 10 != 0:  # a column-header block (never a multiple of 10)
            m = NAME_RE.search(payload)
            pending = m.group(1).decode("latin1") if m else pending
        elif pending is not None and size >= 10:  # the paired data block
            vals = decode_doubles(payload)
            # Non-double columns (text/int — plan item 4) reinterpret as float64
            # garbage; drop them rather than emit nonsense. Two tells: absurd
            # magnitudes (int/float32 payloads) and a printable-ASCII payload
            # (text — real float64 arrays run ~35-40% printable bytes, text
            # >90%). All-NaN stays (empty columns are real).
            if plausible_column(vals, allow_all_nan=True) and not _looks_textual(payload):
                numeric.append((pending, vals))
            elif (rows := decode_inline_text(payload)) is not None:
                text.append((pending, rows))
            elif (rows := decode_report_strings(payload)) is not None:
                report.append((pending, rows))
            elif (salvaged := salvage_column(vals)) is not None:
                # Last resort, ORDER MATTERS: only after the text/report
                # decoders pass — a real double column with a couple of stray
                # junk cells (XRD Book6_A) is salvaged with those cells NaN'd;
                # the report-sheet family must never be stolen into numeric.
                numeric.append((pending, salvaged))
            pending = None
    return numeric, text, report


_PRINTABLE = frozenset(range(0x20, 0x7F)) | {0x09, 0x0A, 0x0D}


def _looks_textual(payload: bytes) -> bool:
    """True when a data block's bytes read as text, not float64 records.

    Two signals must agree: the *non-zero* bytes are across-the-board
    printable (text; float64 mantissa/exponent bytes run well under half —
    but a short column of round values like 10.0 → ``24 40`` can also be
    all-printable), AND the 10-byte record structure is absent — numeric
    records open with a ``00 00`` mask word, text blocks put letters there.
    """
    sample = payload[:400]
    nonzero = [c for c in sample if c != 0]
    if len(nonzero) < 8:
        return False
    if sum(c in _PRINTABLE for c in nonzero) < 0.9 * len(nonzero):
        return False
    n_rec = len(sample) // 10
    masked = sum(1 for k in range(n_rec) if sample[10 * k] == 0 and sample[10 * k + 1] == 0)
    return masked < 0.5 * n_rec


def _label_for(col: str, meta: ColumnMeta | None) -> str:
    """The display label for a value column: its decoded Long Name (Origin
    rich-text escapes translated — see the module docstring) when the windows
    section resolved one, else the bare Origin short designation (A, B, …)."""
    return clean_richtext(meta.long_name) if meta is not None and meta.long_name else col


Columns = list[tuple[str, NDArray[np.float64]]]
TextColumns = list[tuple[str, list[str]]]


def _group_named(pairs: list[tuple[str, _V]]) -> OrderedDict[str, list[tuple[str, _V]]]:
    """Group ``<Book>_<Col>[@sheet]`` names into per-book column lists.

    Shared by numeric column grouping (`_group`) and text column grouping —
    the naming/sheet rule doesn't care what a column's values look like.
    """
    books: OrderedDict[str, list[tuple[str, _V]]] = OrderedDict()
    for name, vals in pairs:
        book, _, col = name.rpartition("_")
        col, _, sheet = (col or "A").partition("@")
        if sheet:  # sheet N>1 becomes its own pseudo-book "<Book>@N"
            book = f"{book or 'Book'}@{sheet}"
        books.setdefault(book or "Book", []).append((col or "A", vals))
    return books


def _group(columns: Columns) -> OrderedDict[str, Columns]:
    return _group_named(columns)


def _inventory(
    books: OrderedDict[str, Columns],
    books_meta: dict[str, BookMeta],
    report_only: OrderedDict[str, TextColumns] | None = None,
) -> list[dict[str, object]]:
    """Book inventory for metadata. ``report_only`` (plan item 4) lists any
    pseudo-book whose columns are entirely Origin's auto-generated
    report-sheet family (e.g. a fit's "FitNL1" sheet with zero plausible
    numeric columns) — without it, such a sheet would be silently absent from
    the inventory despite getting its own DataStruct (see ``_build_book``).
    """
    out = [
        {
            "name": k,
            "long_name": clean_richtext(books_meta[k].long_name) if k in books_meta else k,
            "ncols": len(v),
            "nrows": max((len(a) for _, a in v), default=0),
        }
        for k, v in books.items()
    ]
    for k, v in (report_only or {}).items():
        if k in books:
            continue
        out.append(
            {
                "name": k,
                "long_name": clean_richtext(books_meta[k].long_name) if k in books_meta else k,
                "ncols": len(v),
                "nrows": max((len(rows) for _, rows in v), default=0),
            }
        )
    return out


def _book_long_name(book: str, books_meta: dict[str, BookMeta]) -> str:
    """The book's display title (Origin rich-text escapes translated — see
    the module docstring), with a "(sheet N)" suffix for an extra-sheet
    pseudo-book (``Book@N``)."""
    base_book, _, sheet_no = book.partition("@")
    if sheet_no and base_book in books_meta:
        return f"{clean_richtext(books_meta[base_book].long_name)} (sheet {sheet_no})"
    return clean_richtext(books_meta[book].long_name) if book in books_meta else book


def _build_book(
    book: str,
    cols: Columns,
    books_meta: dict[str, BookMeta],
    inventory: list[dict[str, object]],
    source_format: str = "origin_opj",
    text_cols: TextColumns | None = None,
    report_cols: TextColumns | None = None,
) -> DataStruct:
    """Assemble one workbook into a DataStruct.

    Ragged columns are padded to the book's max length with NaN. The X column
    is the first designation-X column when the windows metadata knows one,
    else the first column; the rest become value columns labelled by their
    long name (falling back to the Origin short designation A, B, …).

    ``text_cols`` (plan item 4) are this book's inline-text columns — never
    part of `.values` (the data contract is numeric); they attach under
    ``metadata["origin_text_columns"]`` keyed by Origin short name (A, B, …).
    ``report_cols`` (plan item 4, report-sheet residue) are this book's
    report-sheet reference-string columns (Notes/Summary/Parameters/RegStats/
    ANOVA "cell://" columns), attached the same way under
    ``metadata["origin_report_sheets"]``.

    A sheet made *entirely* of report-sheet columns (e.g. a fit's "FitNL1"
    report, which typically has zero plausible-numeric columns of its own —
    ``cols`` empty) still gets its own pseudo-book: an empty-data DataStruct
    carrying only the report metadata, rather than being silently omitted.
    """
    if not cols:
        book_long = _book_long_name(book, books_meta)
        meta_empty: dict[str, object] = {
            "source_format": source_format,
            "origin_book": book,
            "origin_book_long": book_long,
            "origin_books": inventory,
            "origin_report_sheets": {c: rows for c, rows in (report_cols or [])},
        }
        return DataStruct(time=np.empty(0), values=np.empty((0, 0)), metadata=meta_empty)

    base_book, _, sheet_no = book.partition("@")
    col_meta = books_meta[base_book].columns if base_book in books_meta and not sheet_no else {}
    maxlen = max((len(v) for _, v in cols), default=0)

    # Locate the independent (X) axis among the DECODED columns. When a book's
    # windows metadata *declares* an X column but that column failed every decode
    # path (so it is absent from ``cols``), do NOT fall back to promoting the
    # first value column to the x-axis: that silently relabels a Y measurement as
    # the independent variable and drops the real X without a trace (Moke.opj
    # Book3; the hc2convert.opj "A6221Lockin*" TDI family — 34 of 74 books). Use
    # a synthetic row-index axis instead, keep every decoded column as a value
    # series, and flag the loss in metadata (``x_column_recovered``).
    decoded_x = next(
        (j for j, (c, _) in enumerate(cols) if (m := col_meta.get(c)) and m.designation == "X"),
        None,
    )
    declared_x = next((c for c, m in col_meta.items() if m.designation == "X"), None)
    x_unrecovered = decoded_x is None and declared_x is not None

    if x_unrecovered:
        ordered = list(cols)
    else:
        x_idx = decoded_x if decoded_x is not None else 0
        ordered = [cols[x_idx]] + [cv for j, cv in enumerate(cols) if j != x_idx]

    def _pad(a: NDArray[np.float64]) -> NDArray[np.float64]:
        return a if len(a) == maxlen else np.concatenate([a, np.full(maxlen - len(a), np.nan)])

    padded = [_pad(v) for _, v in ordered]
    if x_unrecovered:
        # The designated X column is unrecoverable → synthetic 0..N-1 row index
        # as `.time`; every decoded column stays a value series (none consumed).
        time = np.arange(maxlen, dtype=np.float64)
        values = np.column_stack(padded) if padded else np.empty((maxlen, 0))
        value_cols = [c for c, _ in ordered]
        x_meta = None
    else:
        time = padded[0] if padded else np.empty(0)
        values = np.column_stack(padded[1:]) if len(padded) > 1 else np.empty((maxlen, 0))
        value_cols = [c for c, _ in ordered[1:]]
        x_meta = col_meta.get(ordered[0][0]) if ordered else None
    meta = {
        "source_format": source_format,
        "origin_book": book,
        "origin_book_long": _book_long_name(book, books_meta),
        "origin_books": inventory,
        "x_column_name": "" if x_unrecovered else (ordered[0][0] if ordered else "A"),
        "x_column_long": (
            "Row" if x_unrecovered else (_label_for(ordered[0][0], x_meta) if ordered else "")
        ),
        # `x_unit` is the Origin-subsystem key (writer/COM read it); also emit
        # the canonical `x_column_unit` every other parser uses so the plot +
        # .ogs export layers (which read `x_column_unit`) show the x-axis unit.
        # Both translated (rich-text escapes — see module docstring): a Unit
        # row is exactly as free-form as a Long Name.
        "x_unit": clean_richtext(x_meta.unit) if x_meta is not None else "",
        "x_column_unit": clean_richtext(x_meta.unit) if x_meta is not None else "",
        # False when `.time` is a synthetic row index substituted because the
        # designated X column could not be decoded (its long name, when known,
        # is in ``x_column_unrecovered``); True when `.time` is the real X.
        "x_column_recovered": not x_unrecovered,
        # Origin short names of the value columns, in channel order — lets a
        # figure's curve->column binding (opju_curves) map onto `.values`.
        "origin_column_names": value_cols,
        "column_designations": {c: m.designation for c, m in col_meta.items()},
        "column_comments": {
            c: clean_richtext(m.comment) for c, m in col_meta.items() if m.comment
        },
        "origin_text_columns": {c: rows for c, rows in (text_cols or [])},
        "origin_report_sheets": {c: rows for c, rows in (report_cols or [])},
    }
    if x_unrecovered and declared_x is not None:
        # The declared X's long name, so the Inspector can say *which* column
        # was lost (e.g. "Temperature") rather than just that the axis is a row
        # index.
        meta["x_column_unrecovered"] = _label_for(declared_x, col_meta.get(declared_x))
    return DataStruct(
        time=time,
        values=values,
        labels=tuple(_label_for(c, col_meta.get(c)) for c in value_cols),
        units=tuple(
            clean_richtext(col_meta[c].unit) if c in col_meta else "" for c in value_cols
        ),
        metadata=meta,
    )


_ParseResult = tuple[
    OrderedDict[str, Columns],
    OrderedDict[str, TextColumns],
    OrderedDict[str, TextColumns],
    dict[str, BookMeta],
    list[dict[str, object]],
]


def _parse(path: Path, *, raw: bytes | None = None) -> _ParseResult:
    """Decode the project once: numeric/text/report column groups + window
    metadata. ``raw`` lets a caller that already has the file's bytes (e.g.
    :func:`parse_opj`'s callers in ``origin_project/__init__.py``) skip a
    second disk read; ``None`` (the default) reads ``path`` itself, unchanged
    from before."""
    b = path.read_bytes() if raw is None else raw
    if not b.startswith(b"CPYA"):
        raise fallback(path, f"'{path.name}' does not look like a CPYA .opj (bad header).")
    columns, text_columns, report_columns = _columns(b)
    if not columns:
        raise fallback(path, f"no worksheet columns could be decoded from '{path.name}'.")
    books = _group(columns)
    text_books = _group_named(text_columns)
    report_books = _group_named(report_columns)
    books_meta = window_metadata(b)
    return books, text_books, report_books, books_meta, _inventory(books, books_meta, report_books)


def _primary_key(books: OrderedDict[str, Columns]) -> str:
    """The book :func:`read_opj`/:func:`build_opj_primary` treat as *the*
    primary dataset: the largest workbook by total (pre-padding) column
    length, never a sheet pseudo-book (``Book@N``) unless every book is one.

    Extracted from ``read_opj`` so a single :func:`_parse`/:func:`parse_opj`
    result can serve both the primary DataStruct and the full per-book list
    (:func:`build_opj_books`) without parsing the project twice — the routes
    import path (``read_origin_project_all``) needs both.
    """
    primary_pool = [k for k in books if "@" not in k] or list(books)
    return max(primary_pool, key=lambda k: sum(len(v) for _, v in books[k]))


def parse_opj(path: Path, *, raw: bytes | None = None) -> _ParseResult:
    """Public single-parse entry point: the same intermediate :func:`_parse`
    produces, exposed so a caller that needs BOTH the primary book
    (:func:`build_opj_primary`) and every book (:func:`build_opj_books`) —
    the routes import path — can parse the project once and build each
    independently, instead of each of :func:`read_opj`/:func:`read_opj_books`
    parsing it on their own."""
    return _parse(path, raw=raw)


def build_opj_primary(parsed: _ParseResult) -> DataStruct:
    """Build the primary (largest) book's DataStruct from an already-
    :func:`parse_opj`'d project — the same selection :func:`read_opj`
    performs, factored out so it can share a parse with
    :func:`build_opj_books`."""
    books, text_books, report_books, books_meta, inventory = parsed
    primary = _primary_key(books)
    return _build_book(
        primary,
        books[primary],
        books_meta,
        inventory,
        text_cols=text_books.get(primary),
        report_cols=report_books.get(primary),
    )


def build_opj_books(parsed: _ParseResult) -> list[DataStruct]:
    """Build every book's DataStruct from an already-:func:`parse_opj`'d
    project — identical construction (and order) to :func:`read_opj_books`,
    factored out so it can share a parse with :func:`build_opj_primary`.

    A sheet made entirely of report-sheet columns (plan item 4 — e.g. a fit's
    "FitNL1" report) has no plausible-numeric columns at all, so it never
    appears as a key in ``books``; the union with ``report_books`` (and
    ``text_books``, for the analogous inline-text case) below still surfaces
    it as its own pseudo-book rather than dropping the whole sheet.
    """
    books, text_books, report_books, books_meta, inventory = parsed
    keys = list(books)
    keys += [k for k in text_books if k not in books and k not in keys]
    keys += [k for k in report_books if k not in books and k not in keys]
    return [
        _build_book(
            k,
            books.get(k, []),
            books_meta,
            inventory,
            text_cols=text_books.get(k),
            report_cols=report_books.get(k),
        )
        for k in keys
        if books.get(k) or text_books.get(k) or report_books.get(k)
    ]


def read_opj(path: Path) -> DataStruct:
    """The single-DataStruct contract: the largest workbook (inventory in metadata).

    Extra-sheet pseudo-books (``Book@N`` — often fit tables/curves) never win
    the primary slot over measured sheet-1 data, however large they are.
    """
    return build_opj_primary(_parse(path))


def read_opj_books(path: Path) -> list[DataStruct]:
    """Every workbook in the project as its own DataStruct (plan item 3).

    A sheet made entirely of report-sheet columns (plan item 4 — e.g. a fit's
    "FitNL1" report) has no plausible-numeric columns at all, so it never
    appears as a key in ``books``; the union with ``report_books`` (and
    ``text_books``, for the analogous inline-text case) below still surfaces
    it as its own pseudo-book rather than dropping the whole sheet.
    """
    return build_opj_books(_parse(path))
