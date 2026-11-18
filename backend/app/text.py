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
