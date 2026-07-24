# Vendored from quantized-lab v0.11.0 (c34980b82947af3f82f7a9a4ff5692610ba5398f).
# Modified by PL Analyzer Pro only to use the local relative import namespace.
"""Extract per-column long-names/units from the ``.opju`` (CPYUA) windows section.

The CPYUA container's worksheet windows section is not `.opj`'s CPY block
stream (see ``docs/origin_re/opj_windows_section.md``) — it uses its own
tag/length framing that this module does not fully parse. What IS pinned,
validated against Origin's own exported ground truth across five real
corpus files (XAS, RockingCurve, UnpolPlots, "Fixed Lambdas SI", plus the
``rosetta_*`` specimens — 145/145 names, units, and comments matched):

* Every worksheet column carries a 2-byte **plot-designation marker**:
  ``21 51`` for X, ``21 61`` for Y, ``30 61`` for Y-error — the same
  marker-byte + display-code convention `.opj` uses at property-block
  offsets 0x25/0x26 (see ``opj_windows_section.md`` sec 4.1), reused inside
  CPYUA's own framing.
* A fixed-shape run (default column-format doubles) follows every marker,
  then an OPTIONAL length-prefixed embedded blob (``<len><tag=0x01><bytes>
  <NUL>``) carrying that column's ``ColumnInfo``/``ImportFile`` storage
  (only present for imported-file columns — a long file path, possibly
  using Origin's internal string back-reference shorthand which this
  module never tries to decode), then the REAL label record in the SAME
  ``<len:u8><tag:u8><text><NUL>`` shape (``len`` counts tag+text+NUL).
  ``text`` splits on ``\\r\\n`` into long_name/unit/comment (0-3 rows); a
  zero-length text (tag ``0x01``, no ``\\r\\n``) means "no label" (e.g. an
  unlabeled Y column) and some columns carry only a bare long name with no
  ``\\r\\n`` at all (single-row form).
* Every column emits its own marker (+ optional label) record, in true
  sheet column order (A, B, C, ...) — INCLUDING columns that never decode
  as data (e.g. a blank/text column between two decoded numeric ones).
  That is why association is by ORDINAL POSITION within one book's
  contiguous marker run, mapped through Origin's column lettering
  (A, B, ... Z, AA, AB, ... — wide measurement sheets run well past Z),
  rather than by parsing an internal short-name field — no such field was
  pinned for CPYUA (unlike `.opj`'s offset-0x12 short name). Each book is
  anchored INDEPENDENTLY (not via a forward-only cursor): a project's book
  windows are not in decoded-book order, so a monotonic cursor drops every
  book whose window sits before an already-anchored one (the Hc2 project
  interleaves 30+ of them). Anchors are exact, so independent search is safe.
* Each book's own marker run is anchored via ONE OF: (a) the embedded
  ``ColumnInfo``/``ImportFile`` path's filename, alnum-stripped and matched
  against the book's known short name (handles Origin's habit of dropping
  underscores when deriving a book short name from an imported filename,
  e.g. ``bl11_YIGPy_032.dat`` -> book ``bl11YIGPy032``); or (b) a
  ``<len=namelen+2> 00 00 <name>`` window/book-header reference that
  appears even for books never imported from a file (manually-typed
  sheets, e.g. the ``rosetta_*`` specimens).

Positional guessing is NOT used to *detect* a label: every accepted record
matches the exact ``<len><tag><text><NUL>`` byte count PLUS a character-
class + known-internal-token filter (rejects embedded blob fragments like
a truncated ``ResultsLog``/``OriginStorage`` token, which the length-prefix
match alone can accidentally land inside). Association across a book's
columns IS positional, but only after that book's boundary is independently
confirmed by anchor (a) or (b) above — never by scanning the whole file for
ASCII runs. When no anchor is found, or the marker run doesn't cover every
column ``opju_codec.scan_columns`` actually decoded for that book, the book
is left out of the result entirely (A/B/C fallback stays in force) rather
than guessed at.

See ``docs/origin_re/opju_container.md`` for the full byte-level trail.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .opju_codec import tail_start
from .windows import BookMeta, ColumnMeta

__all__ = ["opju_window_metadata"]

_X_MARK = b"\x21\x51"
_Y_MARK = b"\x21\x61"
_YERR_MARK = b"\x30\x61"
# Label / Z / X-error markers, pinned 2026-07-06 by the designations.opju
# by-construction specimen (one column per designation): Label = `21 41`;
# Z and X-error SHARE `20 61` and are told apart by the record's own
# designation code byte (`82 02 <code>`: 1=label 2=Y-error 3=X 4=Z
# 5=X-error; a plain Y stores no code field at all). Before these, a book
# containing ANY such column failed the cover-check and silently lost its
# ENTIRE metadata run (names, units, and the X designation) — the audit's
# whole-book blast radius (#10).
_LABEL_MARK = b"\x21\x41"
_ZX_MARK = b"\x20\x61"  # Z or X-error; resolved via the code byte
_DESIGNATION = {
    "X": "X",
    "Y": "Y",
    "Y-error": "Y-error",
    "label": "label",
    "Z": "Z",
    "X-error": "X-error",
}

# A backslash-delimited filename token, as embedded in a column's ImportFile path.
_FILENAME_RE = re.compile(rb"\\([\w \-]{1,60}?\.[A-Za-z0-9]{2,5})(?=[^\w.]|$)")
# A plausible bare long-name (no unit/comment row): starts with a letter, then
# the punctuation real scientific column names use -- parens/brackets/colons/
# underscores (e.g. "Nb Hc2 (T)", "NiBi_3::R", "temperature: T1",
# "multi[0]:iterator"). Still excludes path/markup chars (backslash, <, >), which
# the _JUNK_MARKERS filter rejects separately, so a length-prefix coincidence
# landing inside a storage blob is still caught. Checked on the DECODED string
# (see _is_single_row_label) so non-ASCII scientific glyphs -- degree, Angstrom,
# micro, ohm, Greek, sub/superscripts -- are accepted; the .opju container is
# UTF-8, so "tilt 45<deg>" arrives as bytes c2 b0 and a byte-only ASCII regex
# both rejected it and (via latin-1) mojibaked it (2026-07-06 genericity audit).
_LABEL_PUNCT = frozenset(" _:()[]./+%#*,-")
# Text containing any of these is inside an embedded storage blob, not a real label.
_JUNK_MARKERS = (b"\\", b"OriginStorage", b"ColumnInfo", b"ImportFile", b"<", b">")
# Single-row candidates that are themselves a fragment of one of these internal
# tokens (e.g. a length-prefix match landing mid-string, "esultsLog") are noise.
_KNOWN_TOKENS = (
    b"ResultsLog",
    b"OriginStorage",
    b"ColumnInfo",
    b"ImportFile",
    b"TREE",
    b"Organizer",
    b"IMGEXP",
    b"AXISTYPE",
    b"Script",
    b"History",
    b"PConst",
)
_MAX_GAP = 600  # max byte spacing between one column-property record and the next


def _zx_designation(b: bytes, mark_pos: int) -> str:
    """Resolve the shared ``20 61`` marker to Z or X-error via the record's
    own designation code (``82 02 <code>`` a few bytes earlier: 4=Z,
    5=X-error). An unresolvable record reads as "Z" (either way the column
    is a non-plottable auxiliary; the marker still COUNTS the column, which
    is what protects the book's metadata run)."""
    j = b.rfind(b"\x82\x02", max(0, mark_pos - 16), mark_pos)
    if j >= 0 and j + 2 < len(b) and b[j + 2] == 5:
        return "X-error"
    return "Z"


def _decode_cell_text(raw: bytes) -> str | None:
    """Decode a column-label cell, or ``None`` if it isn't text.

    The ``.opju`` container stores text as UTF-8 (degree = ``c2 b0``, micro =
    ``c2 b5``, Greek mu = ``ce bc``); fall back to latin-1 for the rare cell
    that is valid latin-1 but not UTF-8. Reject any cell holding a C0 control
    other than TAB/CR/LF — that is a binary/format block, never a label."""
    for enc in ("utf-8", "latin1"):
        try:
            s = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if any(ord(c) < 0x20 and c not in "\t\r\n" for c in s):
            return None
        return s
    return None


def _is_single_row_label(s: str) -> bool:
    """Whether ``s`` is a plausible bare long-name (see ``_LABEL_PUNCT``).

    Unicode-aware: the first char is any letter (incl. Greek/Cyrillic) and the
    rest are alphanumerics, the scientific punctuation set, or ANY non-ASCII
    printable (``ord >= 0x80``) — the glyphs real column names use. Markup/path
    chars (``\\``, ``<``, ``>``) are ASCII and not in the set, so they still
    fail here on top of the ``_JUNK_MARKERS`` pre-filter."""
    if not s or not s[0].isalpha() or len(s) > 60:
        return False
    return all(c.isalnum() or c in _LABEL_PUNCT or ord(c) >= 0x80 for c in s)


def _strip_alnum(s: bytes) -> bytes:
    return re.sub(rb"[^A-Za-z0-9]", b"", s)


def _excel_col(i: int) -> str:
    """0-based column index -> Origin/Excel column letter (0->A, 25->Z, 26->AA...)."""
    letters = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def _filename_anchors(b: bytes, start: int) -> list[tuple[int, bytes, bytes]]:
    """``(position, alnum-stripped-basename, raw-filename)`` per backslash token."""
    out: list[tuple[int, bytes, bytes]] = []
    for m in _FILENAME_RE.finditer(b):
        if m.start() < start:
            continue
        raw = m.group(1)
        base = raw.rsplit(b".", 1)[0]
        out.append((m.start(), _strip_alnum(base), raw))
    return out


def _book_anchor(
    b: bytes, short: str, search_from: int, filename_hits: list[tuple[int, bytes, bytes]]
) -> tuple[int, bytes | None] | None:
    """First ``(position, raw_filename_or_None)`` identifying this book's window section."""
    short_b = short.encode("latin1")
    for pos, stripped, raw in filename_hits:
        if pos >= search_from and stripped == short_b:
            return pos, raw
    header_len = len(short_b) + 2
    if header_len < 256:
        idx = b.find(bytes([header_len]) + b"\x00\x00" + short_b, search_from)
        if idx >= 0:
            return idx, None
    if len(short) >= 4:  # storage-tail reference; too ambiguous for short names alone
        storage_len = len(short_b) + 1
        if storage_len < 256:
            idx = b.find(bytes([storage_len]) + short_b + b"\x00", search_from)
            if idx >= 0:
                return idx, None
    return None


def _gap_text_span(b: bytes, start: int, end: int) -> int:
    """Longest run of consecutive text bytes in ``[start, end)``.

    A text byte is printable ASCII / TAB / CR / LF, or a UTF-8 high byte
    (>= 0x80 — a label glyph). Used only to WIDEN the inter-marker gap
    allowance by the label content actually present, so a long column comment
    (a long contiguous printable run) can't split a book's metadata run. A
    real book boundary is a multi-KB BINARY window header — no comparable
    printable run — so this never merges two books. Framing-agnostic on
    purpose: the comment's length prefix is a multi-byte varint we don't parse
    here, and we don't need to."""

    def _is_text(c: int) -> bool:
        return c in (0x09, 0x0A, 0x0D) or 0x20 <= c <= 0x7E or c >= 0x80

    best = run = 0
    for c in b[start : min(end, len(b))]:
        run = run + 1 if _is_text(c) else 0
        if run > best:
            best = run
    return best


def _parse_label_record(b: bytes, p: int) -> bytes | None:
    """One label record at ``p``: ``<LEB128 length><chunks>`` where each chunk
    is ``<len:1><data>``, non-final chunks are exactly 127 bytes, and the
    concatenated data is ``<text><NUL>``.

    The common short label is the single-chunk case (the old fixed-shape
    read). A >127-byte label — a long column comment — stores a 2-byte
    varint length and 127-byte chunking; the old single-byte read silently
    dropped that column's WHOLE label (long-name included), the §13.2 #13
    residual, pinned by the ``long_comment.opju`` specimen (record:
    varint ``e8 05`` = 744, chunks 127×5 + 103, text 737)."""
    length = b[p]
    off = 1
    if length & 0x80:  # LEB128 continuation bit -> 2-byte varint
        if p + 2 > len(b):
            return None
        length = (length & 0x7F) | (b[p + 1] << 7)
        off = 2
        if length <= 0x7F or length > 4096:  # a real 2-byte varint is >127
            return None
    elif length < 2:
        return None
    end_rec = p + off + length
    if end_rec > len(b):
        return None
    payload = b[p + off : end_rec]
    data = bytearray()
    i = 0
    while i < len(payload):
        clen = payload[i]
        last = i + 1 + clen == len(payload)
        if clen == 0 or (not last and clen != 0x7F) or i + 1 + clen > len(payload):
            return None
        data += payload[i + 1 : i + 1 + clen]
        i += 1 + clen
    if not data or data[-1] != 0:
        return None
    return bytes(data[:-1])


def _find_label(b: bytes, start: int, end: int) -> str | None:
    """First label-shaped record in ``[start, end)``.

    Prefers a ``\\r\\n``-split multi-row label (long_name/unit/comment); falls
    back to a single-row (long-name-only) record when no multi-row match
    exists in range.
    """
    multi = single = None
    limit = min(end, len(b) - 2)
    for p in range(start, limit):
        text = _parse_label_record(b, p)
        if text is None or not text:
            continue
        if any(marker in text for marker in _JUNK_MARKERS):
            continue
        decoded = _decode_cell_text(text)
        if decoded is None:
            continue
        if "\r\n" in decoded:
            multi = decoded
            break
        if single is None and _is_single_row_label(decoded):
            if len(text) >= 4 and any(text in token for token in _KNOWN_TOKENS):
                continue
            single = decoded
    return multi if multi is not None else single


def opju_window_metadata(
    b: bytes, book_columns: Mapping[str, Sequence[str]]
) -> dict[str, BookMeta]:
    """Map book short name -> :class:`~quantized.io.origin_project.windows.BookMeta`.

    ``book_columns`` is the already-decoded ``{book: [col_letter, ...]}``
    ordering (see ``opj._group``) — this function never invents a column
    that ``opju_codec.scan_columns`` didn't independently decode; it only
    attaches a label to it when the book's marker run can be confirmed.
    """
    start = tail_start(b)
    markers = sorted(
        [(m.start(), "X") for m in re.finditer(_X_MARK, b) if m.start() >= start]
        + [(m.start(), "Y") for m in re.finditer(_Y_MARK, b) if m.start() >= start]
        + [(m.start(), "Y-error") for m in re.finditer(_YERR_MARK, b) if m.start() >= start]
        + [(m.start(), "label") for m in re.finditer(_LABEL_MARK, b) if m.start() >= start]
        + [
            (m.start(), _zx_designation(b, m.start()))
            for m in re.finditer(_ZX_MARK, b)
            if m.start() >= start
        ]
    )
    filename_hits = _filename_anchors(b, start)
    books: dict[str, BookMeta] = {}
    # Anchor each book INDEPENDENTLY from the tail start (not a forward-only
    # cursor): a project's book windows are not laid out in decoded-book order
    # (the Hc2 project interleaves them), so a monotonic cursor drops every book
    # whose window section sits before an already-anchored one. Anchors are exact
    # (length-prefixed name / filename basename), so independent search cannot
    # cross-match a different book.
    for book, cols in book_columns.items():
        if not cols:
            continue
        anchored = _book_anchor(b, book, start, filename_hits)
        if anchored is None:
            continue
        anchor, raw_filename = anchored
        candidates = [t for t in markers if t[0] > anchor]
        x_positions = [i for i, t in enumerate(candidates) if t[1] == "X"]
        letter_map: dict[str, tuple[int, str]] | None = None
        run: list[tuple[int, str]] = []
        # The run bound is DERIVED from the column count (the old fixed
        # _MAX_RUN=128 cap silently dropped ALL metadata of a >128-column
        # book — names, units, and the X designation; 2026-07-06 genericity
        # audit). The >_MAX_GAP break remains the real book-boundary signal;
        # len(cols) + slack is only the runaway backstop.
        max_run = len(cols) + 32
        for xi in x_positions:
            attempt = [candidates[xi]]
            j = xi + 1
            while j < len(candidates) and len(attempt) < max_run:
                # The gap to the NEXT column marker is set by how much label
                # content THIS column carries: long_name + unit + comment, and
                # a comment can run to hundreds of chars. So the allowance is
                # _MAX_GAP plus the length of the label record that actually
                # sits in the gap (structural), not a fixed byte cap that a
                # long comment silently overruns -- which used to drop the
                # whole book's metadata (2026-07-06 genericity audit). The
                # real book boundary is a multi-KB window header, far past any
                # single label record, so this never merges two books.
                gap = candidates[j][0] - attempt[-1][0]
                allow = _MAX_GAP + _gap_text_span(b, attempt[-1][0] + 2, candidates[j][0])
                if gap > allow:
                    break
                attempt.append(candidates[j])
                j += 1
            if len(attempt) < len(cols):
                continue
            candidate_map = {_excel_col(i): attempt[i] for i in range(len(attempt))}
            if all(c in candidate_map for c in cols):
                letter_map, run = candidate_map, attempt
                break
        if letter_map is None:
            continue
        long_name = raw_filename.decode("latin1", errors="replace") if raw_filename else book
        columns: dict[str, ColumnMeta] = {}
        for col in cols:
            pos, desig = letter_map[col]
            ordinal = run.index(letter_map[col])
            next_pos = run[ordinal + 1][0] if ordinal + 1 < len(run) else pos + 3000
            label = _find_label(b, pos + 2, min(next_pos, pos + 3000))
            rows = (label.split("\r\n") if label else []) + ["", "", ""]
            columns[col] = ColumnMeta(col, _DESIGNATION.get(desig, "Y"), rows[0], rows[1], rows[2])
        books[book] = BookMeta(book, long_name, columns)
    return books
