"""TrendSparC wordmark + icon mark, as a standalone component.

Both icon paths below are not hand-drawn or estimated - they're extracted
byte-for-byte from the actual logo artwork (`TC 로고.pdf`, provided by the
team) by parsing the PDF's content stream for the icon's two compound vector
paths and converting their PDF-space (Y-up) bezier commands directly into
SVG paths (Y-down), so they are pixel-identical to the source file rather
than a guessed approximation. The source file has exactly two icon path
blocks (everything after them in the content stream is the wordmark text
converted to outlines) - a left 3-square stair-step cluster and a right
2-square overlap cluster, genuinely separated by a gap (confirmed from the
real coordinates, not just visually eyeballed).

The icon fill follows `var(--ts-accent)`, same as the wordmark text color in
`.ts-landing .ts-wordmark` - so both the icon and the wordmark switch
together with the orange/burgundy accent toggle instead of the icon staying
a fixed color while the rest of the brand mark changes. See theme.py.
"""

from __future__ import annotations

_ICON_FILL = "var(--ts-accent)"

# Extracted from TC 로고.pdf's first icon compound path - left 3-square
# stair-step cluster.
_LEFT_CLUSTER_D = (
    "M66.59,96.38 L66.59,39.78 C66.59,38.15 67.92,36.82 69.55,36.82 "
    "L92.53,36.82 C95.93,36.82 98.69,34.07 98.69,30.67 L98.69,6.15 "
    "C98.69,2.76 95.93,0.00 92.53,0.00 L68.02,0.00 C64.62,0.00 61.86,2.76 61.86,6.15 "
    "L61.86,28.35 C61.86,29.98 60.54,31.31 58.90,31.31 L7.55,31.31 "
    "C3.38,31.31 0.00,34.69 0.00,38.86 L0.00,97.40 C0.00,101.57 3.38,104.95 7.55,104.95 "
    "L58.02,104.95 C60.14,104.95 61.86,106.68 61.86,108.80 L61.86,160.41 "
    "C61.86,164.58 65.24,167.96 69.42,167.96 L127.96,167.96 "
    "C132.13,167.96 135.51,164.58 135.51,160.41 L135.51,107.78 "
    "C135.51,103.61 132.13,100.23 127.96,100.23 L70.44,100.23 "
    "C68.31,100.23 66.59,98.51 66.59,96.38 Z"
)

# Extracted from TC 로고.pdf's second icon compound path - right 2-square
# overlap cluster (a mid-size square with a smaller square cut into its
# bottom-right corner), positioned in the same combined coordinate space as
# the left cluster above (both paths share one viewBox, no separate offset
# needed at render time).
_RIGHT_CLUSTER_D = (
    "M163.55,92.36 L163.55,43.95 C163.55,41.67 161.71,39.83 159.43,39.83 "
    "L120.39,39.83 C118.12,39.83 116.27,41.67 116.27,43.95 L116.27,92.32 "
    "C116.27,94.59 118.12,96.44 120.39,96.44 L159.47,96.44 "
    "C160.48,96.44 161.31,97.26 161.31,98.27 L161.31,118.31 "
    "C161.31,120.33 162.95,121.97 164.97,121.97 L180.84,121.97 "
    "C182.86,121.97 184.50,120.33 184.50,118.31 L184.50,97.86 "
    "C184.50,95.84 182.86,94.20 180.84,94.20 L165.39,94.20 "
    "C164.37,94.20 163.55,93.37 163.55,92.36 Z"
)

MARK_SVG = (
    '<svg viewBox="0 0 184.50 167.96" xmlns="http://www.w3.org/2000/svg">'
    f'<path d="{_LEFT_CLUSTER_D}" fill="{_ICON_FILL}"/>'
    f'<path d="{_RIGHT_CLUSTER_D}" fill="{_ICON_FILL}"/>'
    "</svg>"
)


def wordmark_html(large: bool = False) -> str:
    size_class = " ts-wordmark-large" if large else ""
    return (
        f'<div class="ts-wordmark{size_class}"><div class="ts-wordmark-text">'
        '<span class="ts-word-1">Trend</span><span class="ts-word-2">sparC</span></div>'
        f'<span class="ts-mark">{MARK_SVG}</span></div>'
    )
