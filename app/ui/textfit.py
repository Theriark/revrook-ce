"""How wide a line of label text is drawn, so a label is fitted to its room on the
server (THE-1401).

The labels at the ends of the score lines were broken at 20 characters; at 12px and
weight 600 "Design Review Sample" is 153 units wide in Chrome on Linux, whose
system-ui is DejaVu Sans Bold, and the room beside the plot is 140 units, so the
label ran past the drawing and was cut to "Design Review Samp". The widths here are
those of DejaVu Sans Bold, in thousandths of the font size, measured in that browser
on Development: it is the widest of the faces system-ui resolves to (San Francisco,
Segoe UI and Roboto are narrower), so a line fitted with them fits every one of
them. A character not in the table counts as wide as the widest capital, and a
full-width character as one em. charts.js measures the drawn text as well and
shortens a line that still does not fit (a font the table does not foresee).
"""

import unicodedata

ELLIPSIS = "..."
WIDE = 1103
FULL = 1000
# fmt: off
WIDTHS = {
    " ": 348, "!": 456, '"': 520, "#": 837, "%": 1001, "&": 871, "'": 306,
    "(": 457, ")": 457, "*": 522, "+": 837, ",": 379, "-": 415, ".": 379,
    "/": 365, ":": 399, ";": 399, "=": 837, "?": 579, "@": 999, "[": 457,
    "]": 457, "_": 499,
    "a": 674, "b": 715, "c": 592, "d": 715, "e": 677, "f": 405, "g": 715,
    "h": 711, "i": 342, "j": 342, "k": 664, "l": 342, "m": 1041, "n": 711,
    "o": 686, "p": 715, "q": 715, "r": 493, "s": 595, "t": 478, "u": 711,
    "v": 651, "w": 923, "x": 644, "y": 651, "z": 581,
    "A": 773, "B": 761, "C": 733, "D": 829, "E": 682, "F": 682, "G": 820,
    "H": 836, "I": 372, "J": 372, "K": 774, "L": 637, "M": 994, "N": 836,
    "O": 849, "P": 732, "Q": 849, "R": 769, "S": 677, "T": 703, "U": 811,
    "V": 773, "W": 1102, "X": 770, "Y": 723, "Z": 724,
}
# fmt: on
WIDTHS.update(dict.fromkeys("0123456789", 695))


def _char_width(char: str) -> int:
    if char in WIDTHS:
        return WIDTHS[char]
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return FULL
    # An accented letter is as wide as the letter it is built on
    base = unicodedata.normalize("NFKD", char)[:1]
    return WIDTHS.get(base, WIDE)


def text_width(text: str, size: float) -> float:
    """The width of `text` drawn at `size` units, at most (see the module)."""
    return sum(_char_width(char) for char in text) * size / 1000


def shorten(text: str, room: float, size: float) -> str:
    """`text` when it fits `room`, else as many of its words as fit followed by
    "..."; a first word too long on its own is cut between its letters."""
    if text_width(text, size) <= room:
        return text
    words = text.split()
    while len(words) > 1:
        words.pop()
        kept = " ".join(words) + ELLIPSIS
        if text_width(kept, size) <= room:
            return kept
    letters = text
    while letters and text_width(letters.rstrip() + ELLIPSIS, size) > room:
        letters = letters[:-1]
    return letters.rstrip() + ELLIPSIS


def fit_lines(text: str, room: float, size: float, most: int) -> tuple[str, ...]:
    """`text` broken between its words onto at most `most` lines of `room` units;
    what does not fit the last line ends it in "..." (shorten)."""
    lines: list[str] = []
    words = text.split()
    while words and len(lines) < most - 1:
        line = words.pop(0)
        while words and text_width(f"{line} {words[0]}", size) <= room:
            line = f"{line} {words.pop(0)}"
        if text_width(line, size) > room:
            # One word longer than a line: it ends the label
            return (*lines, shorten(line, room, size))
        lines.append(line)
    if words:
        lines.append(shorten(" ".join(words), room, size))
    return tuple(lines) or (text,)
