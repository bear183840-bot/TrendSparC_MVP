"""Loads this package's Solar Pro 3 system prompts from prompts/*.md.

Reads the file fresh on every call rather than caching at import time —
same pattern as sectors/sk_hynix/adapter/analyzer's `_load_system_prompt()`
reading sectors/sk_hynix/prompts/system_prompt.md — so editing a .md file
takes effect on the next call without reimporting Python.
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load(name: str) -> str:
    return (_PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
