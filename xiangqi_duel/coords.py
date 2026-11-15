"""Board geometry: files, ranks, squares and zone helpers."""
from __future__ import annotations

FILES = "abcdefghi"
WIDTH = 9
HEIGHT = 10


def in_board(x, y):
    return 0 <= x < WIDTH and 0 <= y < HEIGHT


def square(x, y):
    """Return the UCCI square name of an (x, y) pair."""
    if not in_board(x, y):
        raise ValueError("square (%r, %r) is off the board" % (x, y))
    return "%s%d" % (FILES[x], y)


def parse_square(text):
    """Parse 'h2' (or an (x, y) pair) into coordinates."""
    if isinstance(text, (tuple, list)) and len(text) == 2:
        try:
            x, y = int(text[0]), int(text[1])
        except (TypeError, ValueError):
            raise ValueError("bad square %r" % (text,))
    else:
        s = str(text).strip().lower().replace(" ", "")
        if len(s) != 2 or s[0] not in FILES or not s[1].isdigit():
            raise ValueError(
                "bad square %r; use file a-i plus rank 0-9, e.g. 'h2'" % (text,)
            )
        x, y = FILES.index(s[0]), int(s[1])
    if not in_board(x, y):
        raise ValueError("square %r is off the board" % (text,))
    return x, y


def in_palace(color, x, y):
    if not 3 <= x <= 5:
        return False
    return 0 <= y <= 2 if color == "red" else 7 <= y <= 9


def crossed_river(color, y):
    """True when rank y is on the opponent's half of the board."""
    return y >= 5 if color == "red" else y <= 4


def home_side(color, y):
    """True when rank y is on color's own half of the board."""
    return y <= 4 if color == "red" else y >= 5

def numeric_square(x, y):
    """1-based numeric coordinate: column 1-9, row 1-10."""
    return "%d-%d" % (x + 1, y + 1)


def parse_coord(text):
    """Accept numeric (3-4) coordinates and legacy UCCI (c2)."""
    import re

    raw = str(text).strip()
    match = re.fullmatch(r"(\d{1,2})\s*[-,\s]\s*(\d{1,2})", raw)
    if match:
        x = int(match.group(1)) - 1
        y = int(match.group(2)) - 1
        if 0 <= x <= 8 and 0 <= y <= 9:
            return x, y
        raise ValueError("coordinate out of range: %r (column 1-9, row 1-10)" % (text,))
    return parse_square(raw)
