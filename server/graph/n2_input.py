"""N2 — Input Parser.

Validates and normalizes the raw job description, computes token estimates,
and builds default section configurations.

Rules:
- JD must be 100–15,000 characters
- HTML tags are stripped via regex
- Token estimate: char_count / 4 (rough GPT tokenization)
- Sections default to summary + experience + projects + skills
"""

from __future__ import annotations

import logging
import re

from server.graph.state import ResumeState
from server.services.types import SectionConfig

_logger = logging.getLogger(__name__)

# Minimum/maximum JD length
MIN_JD_CHARS = 100
MAX_JD_CHARS = 15_000

# Approximate characters-per-token for LLMs
CHARS_PER_TOKEN = 4

# Default sections — all enabled with sensible defaults
DEFAULT_SECTIONS = [
    SectionConfig(name="summary", max_count=None, matched_only=None),
    SectionConfig(name="experience", max_count=None, matched_only=True),
    SectionConfig(name="projects", max_count=3, matched_only=False),
    SectionConfig(name="skills", max_count=None, matched_only=False),
]

_HTML_TAG_RE = re.compile(r"<[^>]*>")


async def run(state: ResumeState) -> ResumeState:
    jd_raw = state.get("jd_raw", "")

    # --- Validation ---
    if not jd_raw or jd_raw.strip() == "":
        raise ValueError("Job description is required")

    clean = _strip_html(jd_raw).strip()
    clean = _normalize_whitespace(clean)

    char_count = len(clean)
    if char_count < MIN_JD_CHARS:
        raise ValueError(
            f"Job description too short: {char_count} characters "
            f"(minimum {MIN_JD_CHARS})"
        )
    if char_count > MAX_JD_CHARS:
        raise ValueError(
            f"Job description too long: {char_count} characters "
            f"(maximum {MAX_JD_CHARS})"
        )

    return ResumeState(
        jd_raw=jd_raw,
        jd_cleaned=clean,
        char_count=char_count,
        estimated_tokens=char_count // CHARS_PER_TOKEN,
        sections=_resolve_sections(state),
    )


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = _HTML_TAG_RE.sub("", text)
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&#39;", "'")
    text = text.replace("&nbsp;", " ")
    return text


def _normalize_whitespace(text: str) -> str:
    """Collapse multiple whitespace chars into single spaces."""
    return re.sub(r"\s+", " ", text)


def _resolve_sections(state: ResumeState) -> list[SectionConfig]:
    """Use user-provided sections or defaults."""
    raw = state.get("sections", [])
    if raw and len(raw) > 0:
        resolved = []
        for s in raw:
            if isinstance(s, dict):
                resolved.append(SectionConfig(**s))
            elif isinstance(s, SectionConfig):
                resolved.append(s)
        if resolved:
            return resolved
    return DEFAULT_SECTIONS
