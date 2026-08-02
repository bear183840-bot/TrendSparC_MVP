"""AudienceProfile contract + loader.

Audience profiles are the single source of truth for how a report is toned
and shaped for a given report recipient. Nothing downstream should ever
branch on an audience's literal name/id — only on fields read from its
profile here.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"


class AudienceProfile(BaseModel):
    audience_id: str
    display_name: str
    tone: str
    detail_level: str
    focus: list[str] = []
    format_preference: str
    report_structure: list[str] = []
    description: str = ""


class AudienceProfileNotFoundError(Exception):
    pass


def load_audience_profile(audience_id: str, profiles_dir: Path = PROFILES_DIR) -> AudienceProfile:
    profile_path = profiles_dir / f"{audience_id}.md"
    if not profile_path.is_file():
        raise AudienceProfileNotFoundError(f"no profile registered for audience '{audience_id}'")

    raw = profile_path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"audience profile '{audience_id}' is missing YAML frontmatter")

    _, frontmatter, body = raw.split("---", 2)
    metadata = yaml.safe_load(frontmatter) or {}
    metadata.setdefault("audience_id", audience_id)
    metadata["description"] = body.strip()
    return AudienceProfile.model_validate(metadata)


def list_audience_ids(profiles_dir: Path = PROFILES_DIR) -> list[str]:
    """User-selectable audience ids only.

    Filenames starting with "_" (e.g. "_default.md") are internal fallback
    profiles — still loadable directly via load_audience_profile(), but
    never offered as one of the selectable personas in the UI.
    """
    if not profiles_dir.is_dir():
        return []
    return sorted(p.stem for p in profiles_dir.glob("*.md") if not p.stem.startswith("_"))
