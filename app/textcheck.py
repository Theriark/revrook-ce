"""Checks on the text a person types, before it is stored or printed."""

import unicodedata

LINE_BREAKS = "\n\r\t"


def control_character(text: str, *, allow_breaks: bool = False) -> str | None:
    """The first control character in the text (NUL, BEL, ...), or None.

    A note may hold tabs and line breaks (allow_breaks); a name may hold neither.
    """
    for character in text:
        if allow_breaks and character in LINE_BREAKS:
            continue
        if unicodedata.category(character) == "Cc":
            return character
    return None


def describe(character: str) -> str:
    """A readable name for a refused character, for example U+0007."""
    return f"U+{ord(character):04X}"
