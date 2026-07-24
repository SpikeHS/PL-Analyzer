# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro only to use the local relative import namespace.
"""The ``.opju`` (CPYUA) worksheet-column codec — canonical Burtscher FPC.

Format facts derived clean-room (no GPL liborigin) from known-content Rosetta
specimens generated with an Origin 2026b trial, then locked against Origin's
own exported ground truth (``tests/test_io_origin_ground_truth.py``): every
``XAS.opju`` column (243/243 values) and 193 ``Hc2 data`` columns decode
bit-exact, plus ``RockingCurve`` axes at 71 and 201 rows.

Each numeric column is an FPC-compressed float64 stream (Burtscher &
Ratanaworabhan, *FPC: A High-Speed Compressor for Double-Precision
Floating-Point Data*, IEEE TC 2009). Two predictors race for every value:

* **FCM** — a value predictor: ``pred = fcm[fh]``;
* **DFCM** — a stride predictor: ``pred = last + dfcm[dh]``.

The encoder XORs the true bits against the closer prediction and stores the
low ``k`` bytes little-endian (the dropped high bytes are the leading zeros).
Every value carries a 4-bit code; two codes pack into one control byte, low
nibble first:

* **bit 3** selects the predictor (0 = FCM, 1 = DFCM),
* **bits 0-2** give the residual byte-count: codes 0-3 store 0-3 bytes and
  codes 4-7 store 5-8 (a count of exactly 4 is unsupported, per the paper),
  so code 0 with either selector (``0x0``/``0x8``) means predictor-exact.

Both hash tables hold ``2**12`` entries and update the textbook FPC way::

    fh = ((fh << 6) ^ (value  >> 48)) & 0xFFF
    dh = ((dh << 2) ^ (stride >> 40)) & 0xFFF

Origin frames each column record as ``0a 05 <varint> ff ff <nrows:varint> 00
<segments>``. Segments open with a ZigZag varint: −m = "m FPC rows", with
``0x0c`` + the stream *inline* and a FRESH predictor state per stream (a
plain column is the single segment ``zigzag(−nrows)``); +k = "k rows of one
repeated value" whose value-spec follows (``0x50``+float64, ``0x1a``/``0x11``
+ the double's top 2/1 bytes, or bare ``0x64`` = 0.0). Segments interleave
freely — Origin run-length-compresses constant runs (total-reflection
plateaus, logger hold-steps) *outside* the FPC streams, and a fully constant
column has no stream at all. Empty numeric cells carry the
``ORIGIN_MISSING`` sentinel and map to NaN.
"""

from __future__ import annotations

import re
import struct

import numpy as np
from numpy.typing import NDArray

from .container import ORIGIN_MISSING, plausible_column

__all__ = ["CodecError", "curve_plot_style", "decode_stream", "scan_columns", "tail_start"]

_MASK = 0xFFFFFFFFFFFFFFFF
_TABLE_MASK = (1 << 12) - 1  # 2**12-entry FCM/DFCM hash tables
_FCM_SHIFT, _FCM_DROP = 6, 48  # fh = ((fh << 6) ^ (value  >> 48)) & mask
_DFCM_SHIFT, _DFCM_DROP = 2, 40  # dh = ((dh << 2) ^ (stride >> 40)) & mask

# A length-prefixed dataset name "<Book>_<Col>[@sheet]" (CPYUA strings carry
# no NUL terminator, so the byte before the match must equal the name
# length). The optional "@<N>" suffix marks a column of sheet N>1 in a
# multi-sheet book (same convention `.opj`'s container.NAME_RE uses) — added
# alongside plan item 4's report-sheet decode, whose fitreport2.opju oracle
# was the first `.opju` specimen with more than one sheet in a book and
# exposed that every extra-sheet column was previously mis-anchored to the
# nearest SHEET-1 name instead (e.g. every FitNL1/FitNLCurve1 column
# collapsing onto "FitBook_B"): the un-suffixed pattern still matched an
# "@2"-suffixed name as a prefix, but the length-prefix byte then disagreed
# with the (shorter) matched length, so it should have failed the anchoring
# check below -- except sheet-1's own un-suffixed names sit right before the
# extra-sheet block and satisfied it instead, silently swallowing every
# later column into whichever sheet-1 name came last.
# Bounds deliberately wider than any corpus maximum (book 62 / column 16 /
# sheet 999 — the old 40/4/99 caps were corpus-shaped and silently dropped a
# column whose name exceeded them; 2026-07-06 genericity audit). The
# length-prefix byte check at the match site is the actual validity gate.
_NAME = re.compile(rb"[A-Za-z][\w ]{0,62}_[A-Za-z0-9]{1,16}(?:@\d{1,3})?")


class CodecError(ValueError):
    """A column stream that doesn't parse under the FPC codec."""


def _width(nibble: int) -> int:
    """Residual byte-count for a 4-bit code — canonical FPC bcode semantics.

    The low 3 bits encode the count of *stored* residual bytes, except that a
    count of exactly 4 is unsupported (rare in practice, per the FPC paper) so
    codes 4-7 mean 5-8 bytes. Code 0 is the predictor-exact case (0 bytes) —
    for either predictor, so ``0x0`` (FCM exact) and ``0x8`` (DFCM exact) both
    carry no payload. An earlier width table ``(c & 7) + 1`` coincided with
    this one for c >= 4 — the only codes clean ramps ever exercise — which let
    hundreds of columns validate bit-exact while ultra-smooth data (codes 0-3)
    misparsed; that was the real cause of the "DFCM-collision" drop-outs.
    """
    c = nibble & 7
    return c if c < 4 else c + 1


def _decode(stream: bytes, nrows: int) -> tuple[NDArray[np.float64], int]:
    """Decode ``nrows`` float64s; return ``(values, bytes_consumed)``."""
    fcm: dict[int, int] = {}
    dfcm: dict[int, int] = {}
    fh = dh = 0
    last = 0
    out: list[int] = []
    pos = 0
    n = len(stream)
    while len(out) < nrows:
        if pos >= n:
            raise CodecError(f"stream exhausted at {len(out)}/{nrows} values")
        ctrl = stream[pos]
        pos += 1
        for nibble in (ctrl & 0xF, ctrl >> 4):
            width = _width(nibble)
            if pos + width > n:
                raise CodecError("residual overruns the buffer")
            resid = int.from_bytes(stream[pos : pos + width] + b"\x00" * (8 - width), "little")
            pos += width
            pred = (last + dfcm.get(dh, 0)) & _MASK if nibble & 8 else fcm.get(fh, 0)
            val = pred ^ resid
            out.append(val)
            stride = (val - last) & _MASK
            fcm[fh] = val
            dfcm[dh] = stride
            fh = ((fh << _FCM_SHIFT) ^ (val >> _FCM_DROP)) & _TABLE_MASK
            dh = ((dh << _DFCM_SHIFT) ^ (stride >> _DFCM_DROP)) & _TABLE_MASK
            last = val
            if len(out) >= nrows:
                break
    vals = np.frombuffer(np.asarray(out, dtype="<u8").tobytes(), dtype="<f8").copy()
    vals[vals == ORIGIN_MISSING] = np.nan  # empty cells → NaN
    return vals, pos


def decode_stream(stream: bytes, nrows: int) -> NDArray[np.float64]:
    """Decode ``nrows`` float64 values from one FPC control+residual stream."""
    return _decode(stream, nrows)[0]


def _read_varint(b: bytes, p: int) -> tuple[int, int]:
    """Read one LEB128 varint at ``p``; return ``(value, next_pos)``."""
    val = shift = 0
    while p < len(b):
        byte = b[p]
        p += 1
        val |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return val, p
    raise CodecError("varint ran off the buffer")


def _zigzag(v: int) -> int:
    """ZigZag-decode a varint (0,1,2,3,… → 0,−1,1,−2,…)."""
    return (v >> 1) ^ -(v & 1)


# Repeat-run value tags: tag byte → payload length. The payload holds the
# float64's TOP bytes (rest zero) — the compact forms cover round values.
_TAG_LEN = {0x50: 8, 0x1A: 2, 0x11: 1, 0x64: 0}


def _decode_record(b: bytes, ff: int) -> tuple[NDArray[np.float64], int] | None:
    """Parse *and* decode the column record whose ``ff ff`` sits at ``ff``.

    Grammar (validated against Origin's own CSV dumps): ``ff ff
    <nrows:varint> 00`` then a segment list. Each segment opens with a ZigZag
    varint:

    * **−m** — m FPC-coded rows; ``0x0c`` and the stream follow *inline*, and
      the predictor state starts FRESH for every stream (the plain column is
      the one-segment case — the old "2·nrows−1 size-ish field" was really
      ``zigzag(−nrows)``);
    * **+k** — k rows of one repeated value; a value-spec tag follows:
      ``0x50`` + float64, ``0x1a``/``0x11`` + the double's top 2/1 bytes
      (rest zero — round values like 1.0, 2.0, 5.0), or bare ``0x64`` = 0.0.

    Segments interleave freely (staircase logger columns alternate hold-runs
    and FPC bursts); a fully constant column is one repeat segment with no
    stream at all. Parsing and decoding fuse because an inline stream's byte
    length is only known by decoding it. Returns ``(values, end)`` with
    ``end`` just past the record's last byte, or None for anything that
    doesn't sum exactly to ``nrows`` — dropped, never guessed at.
    """
    try:
        nrows, p = _read_varint(b, ff + 2)
    except CodecError:
        return None
    if not 2 <= nrows <= 50_000_000:
        return None
    if p >= len(b) or b[p] != 0x00:
        return None
    p += 1
    parts: list[NDArray[np.float64]] = []
    total = 0
    while total < nrows:  # each iteration adds ≥1 row, so this terminates
        try:
            raw, p = _read_varint(b, p)
        except CodecError:
            return None
        count = _zigzag(raw)
        if count > 0:
            if total + count > nrows or p >= len(b):
                return None
            plen = _TAG_LEN.get(b[p])
            if plen is None or p + 1 + plen > len(b):
                return None
            value = struct.unpack("<d", b"\x00" * (8 - plen) + b[p + 1 : p + 1 + plen])[0]
            p += 1 + plen
            parts.append(np.full(count, value, dtype=float))
            total += count
        elif count < 0:
            m = -count
            if total + m > nrows or p >= len(b) or b[p] != 0x0C:
                return None
            try:
                vals, consumed = _decode(b[p + 1 : p + 1 + m * 9 + 16], m)
            except CodecError:
                return None
            parts.append(vals)
            p += 1 + consumed
            total += m
        else:
            return None
    return np.concatenate(parts), p


def _records(b: bytes) -> list[int]:
    """Candidate record markers (``ff ff`` positions), in file order.

    ``0xff 0xff`` also occurs *inside* FPC residual data, so this over-reports;
    :func:`scan_columns` walks the list with a cursor that jumps past each
    decoded record, so the false in-stream markers are skipped.
    """
    out: list[int] = []
    ff = b.find(b"\xff\xff")
    while ff >= 0:
        # The header opens with `0a 05 <varint>` before ff ff. The varint is
        # LEB128-shaped and GROWS with the record (a 120k-row column stores
        # `c0 a9 07` = 120000, three bytes — the old fixed 1-2-byte gate
        # silently rejected every large column's record; 2026-07-06 audit
        # item #16, confirmed by the bigcolumn.opju specimen). Accept any
        # 1..5-byte span that is a WELL-FORMED varint (continuation bytes
        # have the high bit set, the final byte does not) — a structural
        # check, not a size cap.
        for k in (3, 4, 5, 6, 7):
            if ff - k < 0 or b[ff - k] != 0x0A or b[ff - k + 1] != 0x05:
                continue
            varint = b[ff - k + 2 : ff]
            if varint and all(v & 0x80 for v in varint[:-1]) and not varint[-1] & 0x80:
                out.append(ff)
                break
        ff = b.find(b"\xff\xff", ff + 1)
    return out


def _plausible(vals: NDArray[np.float64]) -> bool:
    """Reject any column that shows a decode desync.

    A wrong predictor shatters the float exponent field the same way a
    non-double payload does, so the shared gate applies; all-NaN additionally
    rejects here because a mis-located ``.opju`` record never legitimately
    decodes to nothing but sentinels.
    """
    return plausible_column(vals, allow_all_nan=False)


def scan_columns(b: bytes) -> list[tuple[str, NDArray[np.float64]]]:
    """Decode every ``<Book>_<Col>`` numeric column in a CPYUA ``.opju`` file.

    Records are walked in file order with a cursor: each decoded stream advances
    the cursor past its own bytes, so the false ``ff ff`` markers buried in long
    residual streams are skipped. Every real record is labelled by the nearest
    preceding length-prefixed dataset name (validated on the local corpus: the
    owning ``<Book>_<Col>`` name always leads its record). Streams that fail the
    codec or decode to garbage are dropped — never emitted.
    """
    names = [
        (m.start(), m.group(0).decode("latin1"))
        for m in _NAME.finditer(b)
        if m.start() > 0 and b[m.start() - 1] == len(m.group(0))
    ]
    out: list[tuple[str, NDArray[np.float64]]] = []
    cursor = 0
    for marker in _records(b):
        if marker < cursor:  # a false marker inside an already-decoded record
            continue
        got = _decode_record(b, marker)
        if got is None:
            continue
        vals, end = got
        if not _plausible(vals):
            continue
        prev = [name for pos, name in names if pos < marker]
        if prev:
            out.append((prev[-1], vals))
        cursor = end
    return out


def tail_start(b: bytes) -> int:
    """Byte offset just past the last decoded worksheet-data record.

    Everything before this point is the datasets section (FPC streams, whose
    residual bytes routinely contain byte pairs that coincidentally match the
    windows-section designation markers). ``windows_opju`` uses this to bound
    its marker search to the tail region, avoiding those false positives.
    """
    end = 0
    cursor = 0
    for marker in _records(b):
        if marker < cursor:  # a false marker inside an already-decoded record
            continue
        got = _decode_record(b, marker)
        if got is None:
            continue
        cursor = got[1]
        end = max(end, cursor, marker)
    return end


# ── curve plot-style (item 35 follow-on: line vs scatter) ─────────────────────
#
# A compact-int property tag inside a CPYUA curve's own object body, found at
# a variable forward offset (22-44 bytes past the curve/column token's start
# -- never a fixed offset; see ``opju_curves.py``'s ``_CURVE_RE``/``_extract_
# curves_0x03`` and ``opju_curves_allcols.py``'s ``extract_curves_allcols``,
# both of which locate a curve token first and then call this on its start).
# Validated 135/147 real-corpus curve tokens, 0 disagreements, and 4/4 on the
# ``fig_pairs`` by-construction oracle (scatter/scatter/scatter/line, matching
# LabTalk's ``plot:=201``/``plot:=200``). Lives here, not in ``opju_curves.py``,
# because ``opju_curves_allcols.py`` needs it too and already sits *beneath*
# ``opju_curves.py`` in the import graph (the latter imports the former) --
# importing it the other way round would be circular. ``opju_codec`` is the
# lowest-level module both curve modules already import (``scan_columns``/
# ``_NAME``), so it carries no new dependency edge.
_STYLE_RE = re.compile(rb"\x8f\x01(.)\x83")
_STYLE_WINDOW = 400  # backstop only; the next-token bound below is the gate
_STYLE_BYTES = {0xC8: "line", 0xC9: "scatter"}
# The two curve-token shapes (opju_figure_curves' unified id token and
# opju_curves' 0x03-family token): the style search must STOP at the next
# curve token so a curve with no style tag of its own can never pick up its
# NEIGHBOR's tag. The old fixed 400-byte window was sized against the
# corpus-wide minimum inter-token gap (697 B) — corpus-shaped: a file packing
# curve objects closer than 400 B aliased the next curve's style (2026-07-06
# genericity audit). A false positive of this pattern only SHRINKS the search
# window (worst case an honest ``None``), never widens it.
_NEXT_TOKEN_RE = re.compile(rb"\x01\x01\x01\x80[\x01\x03]|\x01.\x01\x80\x03.\x00", re.DOTALL)


def curve_plot_style(b: bytes, token_start: int) -> str | None:
    """Plot style ("line"/"scatter") of the curve token starting at
    ``token_start``, or ``None`` when no ``8f 01 <style> 83`` tag is found
    before the next curve token (or the 400-byte backstop), or the style
    byte is unrecognized.

    ~8% of real-corpus curve tokens (composite-window duplicate references)
    legitimately have no tag in range -- this returns ``None`` for those
    rather than fabricating a default.
    """
    hi = min(len(b), token_start + _STYLE_WINDOW)
    nxt = _NEXT_TOKEN_RE.search(b, token_start + 8, hi)
    if nxt is not None:
        hi = nxt.start()
    m = _STYLE_RE.search(b, token_start, hi)
    if m is None:
        return None
    return _STYLE_BYTES.get(m.group(1)[0])
