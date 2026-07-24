# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro for local imports and legacy CPYA compatibility.
# See UPSTREAM.md for the complete modification record.
"""Extract per-column metadata from the ``.opj`` windows section.

Worksheet *window definitions* live in the same block stream as the column
data, after the datasets section. Each worksheet window opens with a header
block (``00 00 <BookShort> 00 …``, long name ending at the ``@${`` storage
marker) and contains, per column, a **property block** (≥493 B; designation at
``0x11``, NUL-terminated short name at ``0x12``) immediately followed by a
**label-text block** (``LongName\\r\\nUnit\\r\\nComment``, cut at ``@${``).
Column ``S`` of book ``B`` maps to the dataset named ``"B_S"``.

A property block's byte 0x06 varies with the column's storage flavour --
``0x09`` for a plain sheet-1 column, ``0x0B`` for a formula/derived column
*and* for every column of an auto-generated report sheet (FitLinear/FitNL's
"Parameters"/"Notes"/etc. sheets) -- so it does not distinguish sheet
identity; both values are accepted (plan item: report-sheet leak fix).

**Multi-sheet books** restart column lettering at "A" for each sheet. Their
structural boundary is a sheet/layer sub-header carrying ``Pd<Name>\\0`` at
offset 0xD0. Current CPYA files use a 365-byte header; legacy CPYA 4.2930
uses the same marker in a 341-byte header. Each sheet is mapped separately:
the first to ``<Book>`` and later sheets to ``<Book>@N``, matching the
dataset-name convention used by ``opj.py``. Older files without a supported
``Pd`` marker retain the conservative repeated-name guard and expose only
the first sheet rather than guessing a boundary.

Byte layout validated against the local corpus — see
``docs/origin_re/opj_windows_section.md`` (plan item 1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .container import walk_blocks

__all__ = ["BookMeta", "ColumnMeta", "window_metadata"]

# Origin's published plot-designation enum (format fact).
_DESIGNATION = {
    0: "Y",
    1: "disregard",
    2: "Y-error",
    3: "X",
    4: "label",
    5: "Z",
    6: "X-error",
}


@dataclass(frozen=True)
class ColumnMeta:
    short: str
    designation: str
    long_name: str = ""
    unit: str = ""
    comment: str = ""


@dataclass
class BookMeta:
    short: str
    long_name: str
    columns: dict[str, ColumnMeta] = field(default_factory=dict)
    sheet_name: str = ""


def _cstring(payload: bytes, start: int, limit: int = 48) -> str | None:
    """Printable NUL-terminated ASCII at ``start``, or None."""
    end = payload.find(b"\x00", start, start + limit)
    if end <= start:
        return None
    raw = payload[start:end]
    if not all(0x20 <= c < 0x7F for c in raw):
        return None
    return raw.decode("latin1")


def _is_window_header(payload: bytes) -> str | None:
    """A window-header block starts ``00 00 <Name> 00``; return the name.

    Digit-led names are real (``tree.py``'s module docstring documents
    ``30nmADPNR`` and six digit-led graph names in the corpus, COM-verified),
    so the first-char gate is ``isalnum``, not ``isalpha`` — the old
    alpha-first check silently hid digit-led graph windows from
    ``figures.py`` AND let their internal blocks poison
    ``opj_curves.column_id_map`` (a digit-led graph was not recognized as a
    graph, so its 519-byte curve records were scanned as column storage)."""
    if len(payload) < 150 or payload[0] or payload[1]:
        return None
    name = _cstring(payload, 2, 64)
    return name if name and name[0].isalnum() else None


def _book_long_name(payload: bytes, short: str) -> str:
    """The display title, stored in the header tail.

    v4.3380 headers end the title at an ``@${…}<OriginStorage>`` marker;
    v4.3227 headers have no storage blob — the title is simply the last
    printable run after the fixed-format region (offset > 0x60).
    """
    anchor = payload.find(b"@${")
    if anchor >= 0:
        start = payload.rfind(b"\x00", 0, anchor) + 1
        raw = payload[start:anchor]
        if raw and all(0x20 <= c < 0x7F for c in raw):
            return raw.decode("latin1")
        return short
    runs = [m for m in re.finditer(rb"[\x20-\x7e]{2,}", payload) if m.start() > 0x60]
    if runs:
        cand = runs[-1].group().decode("latin1")
        if cand != short:
            return cand
    return short


def _is_column_block(payload: bytes) -> bool:
    """Robust, version-independent column-property block detector.

    Byte 0x06 is ``0x09`` for a plain (never-recalculated) sheet-1 column and
    ``0x0B`` for a formula/derived column or any report-sheet column -- both
    are real column-property blocks, so both are accepted (a Moke.opj Book4
    Sheet1 measurement had 14/15 columns at ``0x09``; only its one formula
    column, "Normalized1", was ``0x0B`` -- the old ``==0x0B``-only check
    dropped those 14 silently instead of mapping them).
    """
    return (
        len(payload) >= 493
        and payload[0x06] & 0x7F in (0x09, 0x0B)
        and payload[0x25] in (0x21, 0x30)  # 0x30 observed on Y-error columns
        and _cstring(payload, 0x12, 17) is not None
    )


_SHEET_HEADER_SIZES = frozenset((341, 365))
_SHEET_NAME_OFFSET = 0xD0  # 208: fixed offset of the "Pd<Name>" marker


def _is_sheet_header(payload: bytes) -> str | None:
    """A per-sheet (or per-graph-layer) sub-header: the real sheet-boundary
    signal (see module docstring). Supported containers use a 341-byte or
    365-byte block carrying NUL-terminated ``Pd<Name>`` at a fixed offset."""
    if len(payload) not in _SHEET_HEADER_SIZES:
        return None
    if payload[_SHEET_NAME_OFFSET : _SHEET_NAME_OFFSET + 2] != b"Pd":
        return None
    return _cstring(payload, _SHEET_NAME_OFFSET + 2, 40)


def _label_rows(payload: bytes) -> tuple[str, str, str]:
    """Parse a label-text block: LongName / Unit / Comment (missing → "")."""
    text = payload.split(b"\x00", 1)[0]
    cut = text.find(b"@${")
    if cut >= 0:
        text = text[:cut]
    rows = text.decode("latin1", errors="replace").split("\r\n")
    rows += ["", "", ""]
    return rows[0], rows[1], rows[2]


def window_metadata(b: bytes) -> dict[str, BookMeta]:
    """Map book short name → :class:`BookMeta` with per-column names/units.

    ``Pd<Name>`` headers map sheet one to ``<Book>`` and later sheets to
    ``<Book>@N``. Exact pseudo-book keys let ``opj._build_book`` apply each
    sheet's own designations, labels, and units. For containers without a
    recognized marker, a repeated short name still closes collection.
    """
    books: dict[str, BookMeta] = {}
    window_short: str | None = None
    window_long = ""
    current: BookMeta | None = None
    pending: tuple[str, str] | None = None  # (short, designation) awaiting label
    closed = False
    sheets_seen = 0

    def commit(long_name: str = "", unit: str = "", comment: str = "") -> None:
        nonlocal pending, closed
        if pending is not None and current is not None and not closed:
            short, desig = pending
            if short in current.columns:
                # Conservative fallback for containers with no recognized Pd
                # marker: a repeat means a later sheet started, but its exact
                # number cannot be established safely.
                closed = True
            else:
                current.columns[short] = ColumnMeta(short, desig, long_name, unit, comment)
        pending = None

    def select_sheet(sheet_name: str) -> None:
        """Select the exact ``Book``/``Book@N`` metadata target."""

        nonlocal current, closed, sheets_seen
        if window_short is None:
            return
        sheets_seen += 1
        key = window_short if sheets_seen == 1 else f"{window_short}@{sheets_seen}"
        if sheets_seen == 1:
            display_name = window_long
        else:
            suffix = f"sheet {sheets_seen}"
            if sheet_name:
                suffix = f"{suffix}: {sheet_name}"
            display_name = f"{window_long} ({suffix})"
        current = books.setdefault(key, BookMeta(key, display_name))
        current.sheet_name = sheet_name
        closed = False

    for size, payload in walk_blocks(b):
        if size == 0:
            continue
        header_name = _is_window_header(payload)
        sheet_name = _is_sheet_header(payload) if header_name is None else None
        is_col = (
            _is_column_block(payload) if header_name is None and sheet_name is None else False
        )
        if pending is not None:
            if header_name is None and sheet_name is None and not is_col and size < 500:
                commit(*_label_rows(payload))  # the label block for the pending column
                continue
            commit()  # structural block follows — column had no label text
        if header_name is not None:
            window_short = header_name
            window_long = _book_long_name(payload, header_name)
            current = books.setdefault(header_name, BookMeta(header_name, window_long))
            closed = False
            sheets_seen = 0
        elif sheet_name is not None:
            select_sheet(sheet_name)
        elif current is not None and is_col and not closed:
            short = _cstring(payload, 0x12, 17) or "?"
            pending = (short, _DESIGNATION.get(payload[0x11], "Y"))
    commit()
    return books
