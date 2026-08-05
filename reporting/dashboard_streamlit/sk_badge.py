"""SK Group corporate mark, shown next to the top question bar.

Went through a few other approaches before this one, worth recording so the
next edit doesn't re-try them:
  1. Hand-drawn SVG guess from a pasted chat screenshot - too rough, and a
     second freehand attempt still wasn't a reliable trace of the real mark.
  2. The real logo PNG (`assets/sk_logo.png`) rendered as-is via <img> - exact
     shape and color, but a flat raster can't recolor with the app's
     orange/burgundy toggle, and its baked-in opaque white background looked
     like a stray box against the gray/dark header.

This is approach 3: keep the *real* logo's exact silhouette (traced from the
actual asset, not guessed) but drive its color from CSS instead of baking
color into pixels. `assets/sk_logo_mask.png` is `assets/sk_logo.png` with
every near-white pixel (background AND the mark's internal white separator
lines) made transparent via a plain RGB threshold - see the one-off script
used to generate it if this ever needs regenerating from a fresh source
image. That alpha-only image is used as a CSS `mask-image`: the `<span>`'s
own `background` (not the PNG's pixels) supplies the color, so it follows
`var(--ts-accent)` and switches with the orange/burgundy toggle exactly like
the TrendSparC icon does, with no background chip needed (mask transparency
means it sits directly on whatever panel color is behind it).
"""

from __future__ import annotations

import base64
from pathlib import Path

_MASK_PATH = Path(__file__).parent / "assets" / "sk_logo_mask.png"
_MASK_DATA_URI = "data:image/png;base64," + base64.b64encode(_MASK_PATH.read_bytes()).decode("ascii")


def sk_badge_html() -> str:
    return f'<span class="ts-sk-badge" style="--ts-sk-mask:url(\'{_MASK_DATA_URI}\')"></span>'
