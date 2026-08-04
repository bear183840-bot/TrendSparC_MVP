"""TrendSparC wordmark + icon mark, as a standalone component.

The icon is always solid brand orange regardless of context (sidebar vs.
landing); the wordmark text color follows whatever `.ts-wordmark` context it
renders in (black in the sidebar, orange on the landing screen) - see
theme.py. Geometry follows an explicit spec: one 80x80 "body" square (A),
a 40x40 square (B) overlapping A's top-right corner and rising above it, a
60x60 square (C) attached to A's right side, and a 25x25 square (D) sitting
apart from C's top-right corner with a visible gap - deliberately not a
single blob and not a row of same-size tiles.
"""

from __future__ import annotations

_BRAND_ORANGE = "#E8571F"

MARK_SVG = (
    '<svg viewBox="0 0 165 130" xmlns="http://www.w3.org/2000/svg">'
    f'<rect x="0" y="40" width="80" height="80" rx="10" fill="{_BRAND_ORANGE}"/>'
    f'<rect x="50" y="10" width="40" height="40" rx="6" fill="{_BRAND_ORANGE}"/>'
    f'<rect x="70" y="45" width="60" height="60" rx="8" fill="{_BRAND_ORANGE}"/>'
    f'<rect x="135" y="25" width="25" height="25" rx="4" fill="{_BRAND_ORANGE}"/>'
    "</svg>"
)


def wordmark_html(large: bool = False) -> str:
    size_class = " ts-wordmark-large" if large else ""
    return (
        f'<div class="ts-wordmark{size_class}"><div class="ts-wordmark-text">Trend<br>sparC</div>'
        f'<span class="ts-mark">{MARK_SVG}</span></div>'
    )
