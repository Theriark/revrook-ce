"""Checks on the text a person types, before it is stored or printed."""

import unicodedata

LINE_BREAKS = "\n\r\t"
# Format characters (category Cf) are invisible or reorder what is shown: bidi
# controls such as U+202E and U+200F, zero-width space U+200B, word joiner U+2060,
# byte order mark U+FEFF and the tag characters. A text that holds one can read as
# something else, so every text that can reach a report refuses them.
#
# Three format characters are real parts of writing and stay allowed: the
# zero-width non-joiner U+200C and the zero-width joiner U+200D (Persian, Indic
# scripts and emoji sequences) and the soft hyphen U+00AD. They are written as
# escapes so that no editor or transport can drop them.
ALLOWED_FORMAT = frozenset({"‌", "‍", "­"})
# The line and paragraph separators U+2028 and U+2029 are not a normal line break;
# a name may not hold them (a note keeps the behaviour it had).
NAME_ONLY_REFUSED = frozenset({"Zl", "Zp"})


def control_character(text: str, *, allow_breaks: bool = False) -> str | None:
    """The first character the text may not hold, or None.

    Refused everywhere: control characters (NUL, BEL, ...) and format characters
    other than the three that writing needs (see ALLOWED_FORMAT). A note may hold
    tabs and line breaks (allow_breaks); a name may hold neither, and a name may not
    hold a line or paragraph separator.
    """
    for character in text:
        if allow_breaks and character in LINE_BREAKS:
            continue
        category = unicodedata.category(character)
        if category == "Cc":
            return character
        if category == "Cf" and character not in ALLOWED_FORMAT:
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
