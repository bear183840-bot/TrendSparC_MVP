"""One place that decides how a measured number is written on screen.

There were two. `_format_number` in `block_shapes.py` grouped digits, and a
scaling rule lived privately inside the line chart's axis, so the chart said
2,500 만명 while the KPI card beside it said 21,535,256단말장치・단자 for the
same series - the same figure at two magnitudes, with the unit jammed onto
the digits. Every render point now asks this module, so a change to the rule
changes the page rather than one corner of it.

Nothing here rounds a stored value. `MetricPoint.value` is the evidence's own
number and stays that; this only chooses how many of its digits a reader is
shown and which word carries the rest.
"""
from __future__ import annotations

import re
import unicodedata

# Korean magnitude words, largest first. Only exact powers of ten that have a
# word of their own: there is no unit for 10^6, so 25,000,000 is 2,500만, not
# "25M".
SCALES: tuple[tuple[float, str], ...] = ((1e12, "조"), (1e8, "억"), (1e4, "만"))

# Below this a scaled number reads worse than the raw one: 0.25억 is harder
# than 25,000,000 is long. Ten keeps at least two significant digits.
SCALE_MIN = 10.0

# Shares, rates, indices and ordinals are already small numbers whose unit
# *is* the scale. "2.5만%" is not a thing, and neither is 1.2만위.
UNSCALED_UNITS = frozenset({"%", "%p", "％", "배", "점", "위", "건", "개", ""})


def format_number(value: float) -> str:
    """Digit grouping only - trailing-zero-free, never scaled."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.1f}"


def _normalized_unit(unit: str | None) -> str:
    return unicodedata.normalize("NFKC", str(unit or "")).strip()


def scale_for(values: list[float] | tuple[float, ...], unit: str | None) -> tuple[float, str]:
    """`(divisor, magnitude word)` for a set of numbers shown together.

    A set, not one number, because an axis and a bar group have to use one
    scale for every value on them or the lengths stop being comparable.
    """
    if _normalized_unit(unit) in UNSCALED_UNITS:
        return 1.0, ""
    peak = max((abs(value) for value in values), default=0.0)
    for divisor, word in SCALES:
        if peak / divisor >= SCALE_MIN:
            return divisor, word
    return 1.0, ""


# Past this many whole units the fractional digit is noise the reader has to
# skip: 2,153.5만 is not more informative than 2,154만, it is just longer.
_SCALED_DECIMAL_CEILING = 100.0


def scaled_number(value: float, scale: tuple[float, str]) -> str:
    """One value written at an already-chosen scale, e.g. `2,154만`.

    Rounding here is a display choice on a value we are already declaring
    approximate by scaling it; the exact figure is still in the evidence and
    in `MetricPoint.value`.
    """
    divisor, word = scale
    scaled = value / divisor
    if word and abs(scaled) >= _SCALED_DECIMAL_CEILING:
        scaled = round(scaled)
    return f"{format_number(scaled)}{word}"


# A unit that is itself a word needs air between it and the digits, and a
# magnitude word must not run into it: "2,154만단말장치・단자" is unreadable
# and reads as a unit named 만단말장치. Percent and its relatives are written
# tight against the number, the way every source writes them.
_TIGHT_UNITS = frozenset({"%", "%p", "％", "℃", "°"})


def display_value(
    value: float, unit: str | None, scale: tuple[float, str] | None = None
) -> tuple[str, str]:
    """`(number, unit)` for one measurement, ready to place separately.

    Returned as two strings rather than one so a caller can put the unit in
    its own element - smaller, dimmer, on its own line in a KPI card, in the
    axis note on a chart. Callers that want one string join them with
    `joined_value`.

    `scale` is passed in when several values are shown together and must
    share one; omitted, the value is scaled on its own.
    """
    unit_text = _normalized_unit(unit)
    chosen = scale if scale is not None else scale_for([value], unit_text)
    return scaled_number(value, chosen), unit_text


def joined_value(
    value: float, unit: str | None, scale: tuple[float, str] | None = None
) -> str:
    """The same thing as one string, spaced so the unit stays a separate word."""
    number, unit_text = display_value(value, unit, scale)
    if not unit_text:
        return number
    if unit_text in _TIGHT_UNITS:
        return f"{number}{unit_text}"
    return f"{number} {unit_text}"


_SPACED_UNIT_RE = re.compile(r"[가-힣A-Za-z]")


def unit_needs_space(unit: str | None) -> bool:
    """Whether this unit is a word rather than a sign."""
    text = _normalized_unit(unit)
    return bool(text) and text not in _TIGHT_UNITS and bool(_SPACED_UNIT_RE.search(text))
