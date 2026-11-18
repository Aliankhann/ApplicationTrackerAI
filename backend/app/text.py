"""Shared text helpers."""

import unicodedata

_APOSTROPHES = str.maketrans({"\u2019": "'", "\u2018": "'"})


def normalize_text(text: str) -> str:
    """Strip accents and straighten apostrophes so French text and 'résumé' match plain keywords."""
    if not text:
        return ""
    if text.isascii():
        return text
    decomposed = unicodedata.normalize("NFKD", text).translate(_APOSTROPHES)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_BIDI = frozenset(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F))


def strip_controls(text: str) -> str:
    """Drop control, zero-width and bidi characters; tabs and newlines become spaces."""
    out = []
    for c in text:
        if c in "\t\n\r":
            out.append(" ")
        elif c in _BIDI or unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co"):
            continue
        else:
            out.append(c)
    return "".join(out)
