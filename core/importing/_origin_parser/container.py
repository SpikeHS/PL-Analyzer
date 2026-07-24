"""CPY container primitives shared by the Origin ``.opj``/``.opju`` readers.

The ``.opj`` (CPYA) container is a stream of
``<uint32 size LE><0x0A><payload><0x0A>`` blocks (``size==0`` = 5-byte spacer);
worksheet columns, window definitions, and graph windows all live in that one
walkable stream (see ``docs/origin_re/``). Format facts derived clean-room from
local specimens — no GPL code consulted (``docs/origin_project_format.md``).
"""

from __future__ import annotations

import re
import struct
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "ORIGIN_MISSING",
    "NAME_RE",
    "OriginProjectError",
    "decode_doubles",
    "decode_inline_text",
    "decode_report_strings",
    "fallback",
    "plausible_column",
    "salvage_column",
    "walk_blocks",
]

_VIEWER = "the free Origin Viewer (https://www.originlab.com/viewer/)"

# Origin's "missing value" sentinel for an empty numeric cell (-1.23456789e-300);
# stored in the data, not flagged by the mask, so we map it to NaN on decode.
ORIGIN_MISSING = struct.unpack("<d", b"\x0e\x2c\x13\x1c\xfe\x74\xaa\x81")[0]

# A dataset name inside a column-header block: "<book>_<col>[@sheet]\0"
# (the @N suffix marks columns of sheet N>1 in multi-sheet workbooks).
# Bounds are deliberately WIDER than anything corpus-observed (book 62,
# column 16, sheet 999): the old {0,40}/{1,4}/{1,2} caps were corpus maxima,
# and a user-renamed 5+-char column short name (e.g. "Book1_Field") silently
# lost its whole column when the regex refused the name (2026-07-06
# genericity audit). The NUL terminator + the paired data-block structure in
# ``opj.py`` remain the actual validity gates.
NAME_RE = re.compile(rb"([A-Za-z][\w ]{0,62}_[A-Za-z0-9]{1,16}(?:@\d{1,3})?)\x00")


class OriginProjectError(ValueError):
    """An Origin project can't (yet) be read directly; the message explains why
    and how to recover the data (subclasses ValueError so the import route maps
    it to a 422 with the message intact)."""


def fallback(path: Path, detail: str) -> OriginProjectError:
    return OriginProjectError(
        f"{detail} For now, open '{path.name}' in {_VIEWER} and export the "
        f"worksheet(s) to CSV or ASCII, then import that file here."
    )


def walk_blocks(b: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield ``(size, payload)`` for each CPY block after the header line.

    A ``size==0`` block is a section spacer yielded as ``(0, b"")``. Iteration
    stops at the first framing break — the start of the trailing global-storage
    / analysis-log area (which is framed differently).
    """
    nl = b.find(b"\n")
    if nl < 0:
        return
    pos = nl + 1
    n = len(b)
    while pos + 5 <= n:
        size = int.from_bytes(b[pos : pos + 4], "little")
        if b[pos + 4] != 0x0A:  # expected delimiter missing → framing ended
            return
        pos += 5
        if size == 0:
            yield 0, b""
            continue
        if pos + size >= n or b[pos + size] != 0x0A:
            return
        yield size, b[pos : pos + size]
        pos += size + 1


def decode_doubles(data: bytes) -> NDArray[np.float64]:
    """Decode a data block of 10-byte ``<uint16 mask><float64>`` records → values.

    Byte-offset explicit (slice cols 2:10 of each record and view as float64) so
    it is independent of numpy structured-dtype alignment.
    """
    n = len(data) // 10
    rows = np.frombuffer(data, dtype=np.uint8, count=n * 10).reshape(n, 10)
    vals = np.ascontiguousarray(rows[:, 2:]).view("<f8").reshape(n).copy()
    vals[vals == ORIGIN_MISSING] = np.nan  # empty cells → NaN, not a bogus -1e-300
    return vals


_INLINE_TEXT_PRINTABLE = frozenset(range(0x20, 0x7F))


def decode_inline_text(data: bytes) -> list[str] | None:
    """Decode a data block as one short inline-text string per 10-byte record,
    or ``None`` if it doesn't fit that shape (plan item 4 — the non-double
    "text" column case).

    A double column's record is ``<u16 mask><f8 value>``; a **Text & Numeric**
    column reuses the exact same 10-byte record, but the 8-byte value area
    holds a NUL-terminated ASCII/latin-1 string (up to 7 chars) followed by a
    single ``0x00``/``0x01`` tag byte and zero padding out to 8 bytes, instead
    of a raw float64. Pinned against ``hc2convert.opj``: every one of its 58
    dropped "text" columns is exactly this shape, ``prefix="NaN"`` (Origin's
    literal text sentinel for a fit that produced no critical-field value),
    tag byte at value-offset 3 — 112,887 matching records, zero
    counter-examples in a 6-file real-corpus scan. No header type-field byte
    was found that reliably discriminates this from a double column (every
    offset in the 147-byte column-storage header matches between the two);
    this is a content-shape detector, same spirit as ``plausible_column`` and
    the existing ``_looks_textual`` gate.

    A record with no NUL in its 8-byte value area (a string longer than 7
    chars, overflowing into the next record — seen in Origin's FitLinear/
    NLFit auto-generated "Notes"/"Summary" report-sheet columns) makes the
    WHOLE column unsafe to decode this way: return ``None`` rather than emit
    misaligned rows. That family gets a second, dedicated try via
    :func:`decode_report_strings` (a completely different, wider record
    shape) before being dropped for good.
    """
    if not data or len(data) % 10 != 0:
        return None
    n = len(data) // 10
    rows: list[str] = []
    for k in range(n):
        value = data[10 * k + 2 : 10 * k + 10]
        nul = value.find(b"\x00")
        if nul < 0:
            return None
        prefix = value[:nul]
        if prefix and not all(c in _INLINE_TEXT_PRINTABLE for c in prefix):
            return None
        tail = value[nul + 1 :]
        if tail and not (tail[0] in (0x00, 0x01) and all(c == 0 for c in tail[1:])):
            return None
        rows.append(prefix.decode("latin1"))
    return rows


_REPORT_MASK = b"\x01\x00"


def decode_report_strings(data: bytes) -> list[str] | None:
    """Decode a data block as Origin's auto-generated *report-sheet* column
    shape — the ``decode_inline_text`` overflow residue of plan item 4:
    FitLinear/NLFit "Notes"/"Summary"/"Parameters"/"RegStats"/"ANOVA" columns
    whose cells hold a variable-length ``cell://<Section>.<Row>.<Field>``
    reference string (e.g. ``"cell://Parameters.Slope.Value"``) too long for
    ``decode_inline_text``'s fixed 8-byte value area.

    This is a genuinely **different, wider** fixed-per-column record, not a
    variant of the 10-byte double record: ``<u16 mask=0x0001><NUL-terminated
    ASCII/latin-1 string><zero padding>``. The *width* is constant within one
    column (Origin reserves it uniformly, sized to that column's longest
    cell) but **varies column to column** — unlike a double column's constant
    10-byte stride. The ``0x0001`` mask (vs. plain data's/inline-text's
    ``0x0000``) is the tell that discriminates this shape outright; the width
    itself is recovered from the block's own byte content (the spacing
    between consecutive mask markers), then the whole block is re-validated
    at that width before being accepted — a coincidental short match never
    survives more than one row's validation.

    Pinned against ``hc2convert.opj``'s 407 previously honest-dropped
    report-sheet columns (Notes/Input/Parameters/RegStats/Summary/ANOVA
    families, widths from 21 bytes up to 45+ depending on the longest
    ``cell://`` string in that column): **407/407 decode cleanly, 0
    validation failures, 0 collisions with the 10-byte double/inline-text
    shapes** (both already ruled out a data block before this is tried).
    Recovers the *reference string* naming which fit statistic a report cell
    represents — not the fit's computed number itself (e.g. a Slope's actual
    value); that is a separate, harder gap documented in
    ``docs/origin_project_format.md`` "Non-double column values".
    """
    n = len(data)
    if n < 3:
        return None
    idxs: list[int] = []
    i = data.find(_REPORT_MASK)
    while i >= 0:
        idxs.append(i)
        i = data.find(_REPORT_MASK, i + 1)
    if not idxs or idxs[0] != 0:
        return None  # every record must open with the mask, starting at byte 0
    width = n if len(idxs) == 1 else min(idxs[k + 1] - idxs[k] for k in range(len(idxs) - 1))
    if width < 3 or n % width != 0:
        return None
    rows: list[str] = []
    for k in range(n // width):
        rec = data[width * k : width * k + width]
        if rec[:2] != _REPORT_MASK:
            return None
        value = rec[2:]
        nul = value.find(b"\x00")
        if nul < 0:
            return None
        text, pad = value[:nul], value[nul + 1 :]
        if any(pad) or not all(c in _INLINE_TEXT_PRINTABLE for c in text):
            return None
        rows.append(text.decode("latin1"))
    return rows


def plausible_column(vals: NDArray[np.float64], *, allow_all_nan: bool = False) -> bool:
    """Reject a decoded column whose values betray a non-double payload.

    Text / integer / float32 columns (the 147-byte column header carries a
    type field the readers don't decode yet — plan item 4) reinterpret as
    float64 garbage: subnormals (|v| ≲ 1e-300) and absurd magnitudes
    (|v| ≳ 1e290) that real instrument data never contains. Dropping the whole
    column on the first such value is honest-absent; silent garbage is worse
    than a gap. ``allow_all_nan`` keeps genuinely empty columns (the ``.opj``
    reader pads ragged books with them).
    """
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return allow_all_nan
    mag = np.abs(finite)
    wrecked = ((mag < 1e-290) & (finite != 0.0)) | (mag > 1e290)
    return not bool(np.any(wrecked))


# A real double column may carry a couple of stray junk cells (denormals in the
# missing-sentinel magnitude band) without being a non-double payload — XRD.opj
# Book6_A (1543 2-theta values + 4 denormals) is the measured case. True garbage
# (text/int reinterpretations) runs >=5% wrecked across the corpus; the gap
# between <=0.26% (real) and >=0.83% (the report-sheet family, which the
# text/report decoders claim FIRST) motivates the tight bound below.
_SALVAGE_MAX_FRAC = 0.005
_SALVAGE_MAX_CELLS = 4


def salvage_column(vals: NDArray[np.float64]) -> NDArray[np.float64] | None:
    """``vals`` with stray wrecked cells masked to NaN, or None if not salvageable.

    Last-resort classification (after the text and report decoders have
    passed): accepts only columns whose wrecked cells are both rare
    (<= 0.5% of finite values) and few (<= 4 absolute) — measured to separate
    real columns with junk cells from every true-garbage column in the corpus.
    """
    finite_mask = np.isfinite(vals)
    finite = vals[finite_mask]
    if finite.size == 0:
        return None
    mag = np.abs(vals)
    wrecked = np.isfinite(vals) & (((mag < 1e-290) & (vals != 0.0)) | (mag > 1e290))
    n = int(wrecked.sum())
    if n == 0 or n > _SALVAGE_MAX_CELLS or n / finite.size > _SALVAGE_MAX_FRAC:
        return None
    out = vals.copy()
    out[wrecked] = np.nan
    return out
