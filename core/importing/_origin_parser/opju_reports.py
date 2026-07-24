# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro only to use the local relative import namespace.
"""Origin auto-generated report-sheet columns for ``.opju`` (CPYUA) — plan
item 4's report-sheet residue, the ``.opju`` sibling of ``opj.py``'s
``decode_report_strings`` (``container.py``).

Origin's FitLinear/NLFit X-Functions auto-generate report sheets ("FitNL1",
"FitLinearCurve1", …) whose cells hold a variable-length
``cell://<Section>.<Row>.<Field>`` reference string (e.g.
``"cell://Parameters.Slope.Value"``, naming *which* fit statistic that cell
represents) rather than a plain float64. ``.opj``'s version of this family
overflows a fixed 8-byte value area (``container.decode_inline_text`` has to
drop it); ``.opju`` stores the SAME conceptual content in its own record
framing, sharing ``opju_codec``'s ``0a 05 <…> ff ff <…>`` marker but taking a
completely different branch after it.

**The grammar** (pinned against ``specimens/fitreport2.opju`` — a known
linear fit, x=1..8, slope -1.5, intercept 9.5 — whose ``FitNL1`` report sheet
has 28 columns, ``FitNLCurve1`` has 11): a normal numeric record is ``ff ff
<varint> 00 <ZigZag-varint segments>`` (``opju_codec``'s grammar: the byte
right after the row-count varint is ``0x00``, then the segment list decodes
straight to float64s). A REPORT column instead has ``0x01`` at that exact
position — the discriminator, checked at the same byte offset the numeric
codec already tests. What follows is *not* ``opju_codec``'s FPC/repeat
segment grammar at all: a single ZigZag-varint segment count, then, if
negative (``-m``), ``m`` consecutive ``<len:u8><ASCII bytes>`` strings
(``len=0`` is a valid, blank report cell — most report columns hold only a
handful of populated rows out of the segment's ``m``). A positive segment
count was observed on 2 of ``FitNL1``'s 28 columns (its first two, with no
``cell://`` content at all) and its shape is not understood — those columns
are honestly dropped, never guessed at.

**Validation:** every one of ``FitNL1``'s 26 populated columns decodes
cleanly (the reference strings match exactly what
``tools/origin_trial/generate_specimens3.py``'s ``fitreport2`` generator
produced — ``Notes.*`` metadata, ``Input.R1/R2.C1..C4``,
``Parameters.A/B/xintercept.{Value,Error,tValue,Prob,Dependency}``,
``RegStats.C1.*``, ``Summary.R1.*``, ``ANOVAs.*``); the 2 non-text columns
are honestly dropped. **What this does NOT recover:** the fit's actual
computed numbers (e.g. Slope = -1.5) are not present as a plain float64
anywhere near these records (checked directly: neither raw nor FPC-compact
encodings of 9.5/-1.5 appear in the report-sheet byte range) — Origin
appears to cache them in a separate internal structure this module does not
decode. See ``docs/origin_project_format.md`` "Non-double column values" for
the full writeup and the byte-level trail.
"""

from __future__ import annotations

from .opju_codec import (
    _NAME,
    CodecError,
    _read_varint,
    _records,
    _zigzag,
)

__all__ = ["scan_report_columns"]

_PRINTABLE = frozenset(range(0x20, 0x7F))
_MAX_ROWS = 500  # generous ceiling for a report sheet's row count (real corpus: <= 11)
_MAX_STRLEN = 200  # generous ceiling for one reference string (real corpus: <= 34 chars)


def _decode_report_record(b: bytes, marker: int) -> list[str] | None:
    """Decode one report-column record at a ``ff ff`` marker (``marker`` is
    the byte offset of the first ``0xff``), or ``None`` if it isn't this
    shape or fails validation.

    Shares the row-count varint read with ``opju_codec._decode_record`` but
    diverges the instant the following byte is ``0x01`` instead of ``0x00``
    — the two codecs are mutually exclusive by construction (gated on the
    same byte), so this never intercepts a record ``opju_codec.scan_columns``
    would otherwise decode.
    """
    try:
        _row_count, p = _read_varint(b, marker + 2)
    except CodecError:
        return None
    if p >= len(b) or b[p] != 0x01:  # 0x00 = a plain numeric record, not ours
        return None
    p += 1
    try:
        raw, p = _read_varint(b, p)
    except CodecError:
        return None
    count = _zigzag(raw)
    if count >= 0:
        return None  # a positive/blank-fill segment -- shape not understood, honest drop
    m = -count
    if not 1 <= m <= _MAX_ROWS:
        return None
    rows: list[str] = []
    for _ in range(m):
        if p >= len(b):
            return None
        length = b[p]
        p += 1
        if length > _MAX_STRLEN or p + length > len(b):
            return None
        raw_bytes = b[p : p + length]
        p += length
        if not all(c in _PRINTABLE for c in raw_bytes):
            return None
        rows.append(raw_bytes.decode("latin1"))
    return rows


def scan_report_columns(b: bytes) -> list[tuple[str, list[str]]]:
    """Every ``<Book>_<Col>[@sheet]`` report-sheet column in a CPYUA file.

    Reuses ``opju_codec``'s record-marker scan (``_records``) and the same
    "nearest preceding length-prefixed dataset name" anchoring rule
    ``scan_columns`` uses; the two functions never compete for the same
    marker (see ``_decode_report_record``'s docstring), so this can run as an
    entirely independent second pass with no cursor coordination needed.
    """
    names = [
        (m.start(), m.group(0).decode("latin1"))
        for m in _NAME.finditer(b)
        if m.start() > 0 and b[m.start() - 1] == len(m.group(0))
    ]
    out: list[tuple[str, list[str]]] = []
    for marker in _records(b):
        rows = _decode_report_record(b, marker)
        if rows is None:
            continue
        prev = [name for pos, name in names if pos < marker]
        if prev:
            out.append((prev[-1], rows))
    return out
