"""Pieces, colours, glyphs and stable piece identifiers.

Every piece keeps one identifier for its whole life, e.g. red_horse_1 or
black_advisor_2.  Identifiers are assigned per colour and per piece type,
ordered by file a -> i (the same order for both colours), so they are
deterministic and easy to talk about.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .coords import square

RED = "red"
BLACK = "black"
COLORS = (RED, BLACK)

GENERAL = "general"
ADVISOR = "advisor"
ELEPHANT = "elephant"
HORSE = "horse"
CHARIOT = "chariot"
CANNON = "cannon"
SOLDIER = "soldier"

TYPES = (GENERAL, ADVISOR, ELEPHANT, HORSE, CHARIOT, CANNON, SOLDIER)

# UCCI / standard Xiangqi FEN letters (lowercase = black, uppercase = red).
FEN_LETTER = {
    CHARIOT: "r",
    HORSE: "n",
    ELEPHANT: "b",
    ADVISOR: "a",
    GENERAL: "k",
    CANNON: "c",
    SOLDIER: "p",
}
LETTER_TYPE = {v: k for k, v in FEN_LETTER.items()}

# Decorative glyphs used on the board.
GLYPH = {
    RED: {
        GENERAL: "帥", ADVISOR: "仕", ELEPHANT: "相", HORSE: "馬",
        CHARIOT: "車", CANNON: "炮", SOLDIER: "兵",
    },
    BLACK: {
        GENERAL: "將", ADVISOR: "士", ELEPHANT: "象", HORSE: "馬",
        CHARIOT: "車", CANNON: "砲", SOLDIER: "卒",
    },
}

# Names used when writing moves in Chinese notation.
NAME_ZH = {
    RED: {
        GENERAL: "帅", ADVISOR: "仕", ELEPHANT: "相", HORSE: "马",
        CHARIOT: "车", CANNON: "炮", SOLDIER: "兵",
    },
    BLACK: {
        GENERAL: "将", ADVISOR: "士", ELEPHANT: "象", HORSE: "马",
        CHARIOT: "车", CANNON: "炮", SOLDIER: "卒",
    },
}
COLOR_ZH = {RED: "红", BLACK: "黑"}


@dataclass(frozen=True)
class Piece:
    """An immutable piece at a given square."""

    id: str
    color: str
    type: str
    x: int
    y: int

    @property
    def square(self):
        return square(self.x, self.y)

    @property
    def glyph(self):
        return GLYPH[self.color][self.type]

    @property
    def name_zh(self):
        return NAME_ZH[self.color][self.type]

    def to_dict(self):
        return {
            "id": self.id,
            "color": self.color,
            "type": self.type,
            "x": self.x,
            "y": self.y,
            "square": self.square,
            "glyph": self.glyph,
            "name": self.name_zh,
        }


CN_DIGITS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

COLOR_ALIASES = {
    "red": RED, "红": RED, "红方": RED, "紅": RED,
    "black": BLACK, "黑": BLACK, "黑方": BLACK,
}

TYPE_ALIASES = {
    "general": GENERAL, "king": GENERAL, "k": GENERAL,
    "帅": GENERAL, "帥": GENERAL, "将": GENERAL, "將": GENERAL,
    "advisor": ADVISOR, "guard": ADVISOR, "a": ADVISOR,
    "士": ADVISOR, "仕": ADVISOR,
    "elephant": ELEPHANT, "bishop": ELEPHANT, "b": ELEPHANT,
    "象": ELEPHANT, "相": ELEPHANT,
    "horse": HORSE, "knight": HORSE, "n": HORSE, "h": HORSE,
    "马": HORSE, "馬": HORSE,
    "chariot": CHARIOT, "rook": CHARIOT, "r": CHARIOT,
    "车": CHARIOT, "車": CHARIOT,
    "cannon": CANNON, "c": CANNON,
    "炮": CANNON, "砲": CANNON, "包": CANNON,
    "soldier": SOLDIER, "pawn": SOLDIER, "p": SOLDIER,
    "卒": SOLDIER, "兵": SOLDIER,
}

_COLOR_SORTED = sorted(COLOR_ALIASES, key=len, reverse=True)


def normalize_piece_id(text, default_color=None):
    """Turn user / LLM input into a canonical piece id.

    Accepts red_horse_1, redhorse1, 红马1, horse_1 (with a default colour)
    and similar spellings.  Raises ValueError when the text cannot be
    understood.
    """
    raw = str(text).strip().lower().replace("-", "_").replace(" ", "")
    if not raw:
        raise ValueError("empty piece id")

    index = None
    m = re.search(r"([0-9]+|[一二三四五六七八九])$", raw)
    if m:
        token = m.group(1)
        index = int(token) if token.isdigit() else CN_DIGITS[token]
        raw = raw[: m.start()]

    color = default_color
    for alias in _COLOR_SORTED:
        if raw.startswith(alias) and len(raw) > len(alias):
            color = COLOR_ALIASES[alias]
            raw = raw[len(alias):]
            break

    type_token = raw.strip("_")
    piece_type = TYPE_ALIASES.get(type_token)
    if piece_type is None:
        piece_type = TYPE_ALIASES.get(type_token.rstrip("子棋"))
    if piece_type is None:
        raise ValueError("unknown piece id %r" % (text,))
    if color is None:
        raise ValueError(
            "piece id %r has no colour; use e.g. 'red_horse_1'" % (text,)
        )
    if index is None:
        return "%s_%s" % (color, piece_type)
    return "%s_%s_%d" % (color, piece_type, index)
