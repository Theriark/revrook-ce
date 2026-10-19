"""Checks on the text a person types, before it is stored or printed."""

import unicodedata

LINE_BREAKS = "\n\r\t"
# Format characters (bidi overrides such as U+202E, zero-width U+200B, U+FEFF) and the
# line and paragraph separators U+2028 and U+2029 are invisible or reorder what is
# shown, so a name that holds one can pass for another name.
NAME_ONLY_REFUSED = frozenset({"Cf", "Zl", "Zp"})


def control_character(text: str, *, allow_breaks: bool = False) -> str | None:
    """The first control character in the text (NUL, BEL, ...), or None.

    A note may hold tabs and line breaks (allow_breaks); a name may hold neither,
    and a name may not hold a format character or a line or paragraph separator.
    """
    for character in text:
        if allow_breaks and character in LINE_BREAKS:
            continue
        category = unicodedata.category(character)
        if category == "Cc":
            return character
        if not allow_breaks and category in NAME_ONLY_REFUSED:
            return character
    return None


def normalise_breaks(text: str) -> str:
    """The text with every line break as LF.

    A browser counts a line break in a textarea as one character for maxlength but
    sends it as CRLF, so the server counts and stores the text with LF only.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def describe(character: str) -> str:
    """A readable name for a refused character, for example U+0007."""
    return f"U+{ord(character):04X}"
