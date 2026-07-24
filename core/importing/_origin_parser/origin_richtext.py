"""Origin LabTalk rich-text (escape-code) → plain display text.

Origin stores axis titles, legend labels, and text annotations with inline
formatting escapes (LabTalk "text object" syntax). Extracting the raw bytes
(``figures.py``) recovers the string *with* those escapes, e.g. an XRD x-axis
title comes back as ``2\\g(q \\(40))degrees)`` — which, shown verbatim, reads
as literal backslash noise rather than "2θ (degrees)". This module decodes the
display-affecting escapes so a recreated plot's labels match Origin.

Handled escapes:
  ``\\g(...)``            Symbol-font run → Greek letters (q→θ, a→α, m→μ, …)
  ``\\(NNN)``             insert the character with decimal code NNN
  ``\\(xHHHH)``           insert the character with hex code HHHH — Origin's
                         Unicode form (how a ``.opj``-container Save-As stores
                         non-ANSI characters, e.g. ``\\(x2225)`` → ∥; observed
                         live in hc2convert.opj's converted axis titles)
  ``\\+(...)`` / ``\\-(...)``  super-/sub-script → Unicode super/subscripts
  ``\\b(...)`` ``\\i(...)`` ``\\u(...)`` ``\\f:Font(...)`` ``\\c<n>(...)``
                         bold/italic/underline/font/colour → keep inner text

Left untouched: ``%(...)`` data-reference substitutions (e.g. a legend's
auto-label ``%(2)`` means "dataset 2's name" — a reference, not display text)
and any shape we don't recognise (we degrade to the raw string, never worse).

Pure library: str in → str out. No project imports.
"""

from __future__ import annotations

# Adobe/Origin "Symbol" font: Latin code point → the Greek glyph it displays.
_SYMBOL_GREEK: dict[str, str] = {
    "a": "α", "b": "β", "g": "γ", "d": "δ", "e": "ε", "z": "ζ", "h": "η",
    "q": "θ", "i": "ι", "k": "κ", "l": "λ", "m": "μ", "n": "ν", "x": "ξ",
    "o": "ο", "p": "π", "r": "ρ", "s": "σ", "t": "τ", "u": "υ", "f": "φ",
    "c": "χ", "y": "ψ", "w": "ω", "v": "ς", "j": "ϕ",
    "A": "Α", "B": "Β", "G": "Γ", "D": "Δ", "E": "Ε", "Z": "Ζ", "H": "Η",
    "Q": "Θ", "I": "Ι", "K": "Κ", "L": "Λ", "M": "Μ", "N": "Ν", "X": "Ξ",
    "O": "Ο", "P": "Π", "R": "Ρ", "S": "Σ", "T": "Τ", "U": "Υ", "F": "Φ",
    "C": "Χ", "Y": "Ψ", "W": "Ω",
}  # fmt: skip
_GREEK_TABLE = {ord(k): v for k, v in _SYMBOL_GREEK.items()}
_SUP = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
_SUB = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")


def _codepoint(code: str) -> int | None:
    """The character code of a ``\\(...)`` escape body: decimal (``40``) or
    hex with an ``x`` prefix (``x2225`` — Origin's Unicode form, see the
    module docstring). ``None`` when the body is neither shape, or falls
    outside Unicode's assignable range (malformed → literal-paren fallback).
    """
    if code.isdigit():
        value = int(code)
    elif code[:1] in ("x", "X") and len(code) > 1:
        try:
            value = int(code[1:], 16)
        except ValueError:
            return None
    else:
        return None
    return value if 0 <= value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF else None


def _apply_run(control: str, inner: str) -> str:
    """Render a ``\\<control>(inner)`` run's already-decoded inner text."""
    if control == "g":
        return inner.translate(_GREEK_TABLE)
    if control == "+":
        return inner.translate(_SUP)
    if control == "-":
        return inner.translate(_SUB)
    # b / i / u / f:Font / c<n> / anything else: drop the styling, keep text.
    return inner


def _render(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        # \(NNN) / \(xHHHH) — a character-code escape (atomic: its own parens).
        if i + 1 < n and s[i + 1] == "(":
            close = s.find(")", i + 2)
            code = s[i + 2 : close] if close != -1 else ""
            cp = _codepoint(code) if close != -1 else None
            if cp is not None:
                out.append(chr(cp))
                i = close + 1
            else:
                out.append("(")  # malformed — treat as a literal paren
                i += 2
            continue
        # \<control>(...) — a formatting run; control is the text up to '('.
        k = s.find("(", i + 1)
        if k == -1:  # dangling backslash-escape (e.g. a lone "\n"): drop the "\"
            out.append(s[i + 1] if i + 1 < n else "")
            i += 2
            continue
        control = s[i + 1 : k]
        j, depth = k + 1, 1  # find the matching ')' of the run's opening '('
        while j < n and depth:
            if s[j] == "\\" and j + 1 < n:
                if s[j + 1] == "(":  # nested \(NNN) — skip the whole atom
                    inner_close = s.find(")", j + 2)
                    j = inner_close + 1 if inner_close != -1 else j + 2
                    continue
                j += 2  # other escaped char
                continue
            if s[j] == "(":
                depth += 1
            elif s[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            # Unterminated run — malformed; bail so clean_richtext() returns the
            # raw string unchanged rather than Symbol-mapping the rest of the line.
            raise ValueError("unterminated Origin rich-text run")
        out.append(_apply_run(control, _render(s[k + 1 : j])))
        i = j + 1
    return "".join(out)


def clean_richtext(s: str) -> str:
    """Decode Origin rich-text escapes in ``s`` to plain display text.

    Idempotent-ish and total: strings with no ``\\`` escapes return unchanged,
    and any parse error degrades to the raw input (never makes it worse).

    >>> clean_richtext("2\\\\g(q \\\\(40))degrees)")
    '2θ (degrees)'
    >>> clean_richtext("Intensity (arb. units)")
    'Intensity (arb. units)'
    """
    if "\\" not in s:
        return s
    try:
        return _render(s)
    except Exception:
        return s
