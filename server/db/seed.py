"""Seed the knowledge graph from the existing resume .tex file.

Parses E_Hemanth_Nagesh.tex to extract:
- Roles (work experience entries)
- Projects (from PROJECTS section)
- Skills (from TECHNICAL SKILLS section grouped by category)
- Certifications (from CERTIFICATIONS section)
- Links between roles/projects/skills

Usage:
    python -m server.db.seed
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from server.config import get_config
from server.services.database import DatabasePool
from server.db.queries import (
    create_project, create_skill, create_role, create_certification,
    link_project_skill, link_role_project,
)
from server.db.migrations import run_migrations

_logger = logging.getLogger(__name__)

RESUME_PATH = Path(__file__).resolve().parents[2] / "E_Hemanth_Nagesh.tex"

# ---------------------------------------------------------------------------
# Regex-based section extraction (handles \section{NAME} and \section {NAME})
# ---------------------------------------------------------------------------

_SECTION_PATTERN = re.compile(
    r"\\section\s*\{([^}]+)\}",
    re.DOTALL,
)


def _extract_section(tex: str, name: str) -> str:
    r"""Extract everything between \section{name} and the next \section{...}.

    Handles both \section{NAME} and \section {NAME} formatting.
    """
    # Find all section boundaries
    sections = list(_SECTION_PATTERN.finditer(tex))
    for i, m in enumerate(sections):
        if m.group(1).strip() == name.strip():
            start = m.end()
            end = sections[i + 1].start() if i + 1 < len(sections) else len(tex)
            return tex[start:end]
    return ""


def _find_braced_groups(text: str, start_pos: int = 0) -> list[tuple[int, int, str]]:
    """Find all top-level {content} groups, handling nested braces.

    Returns list of (start, end, inner_content) tuples.
    """
    results = []
    i = start_pos
    while i < len(text):
        if text[i] == "{":
            depth = 1
            j = i + 1
            while j < len(text) and depth > 0:
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                j += 1
            results.append((i, j, text[i + 1 : j - 1]))
            i = j
        else:
            i += 1
    return results


def _parse_roles(tex: str) -> list[dict[str, Any]]:
    """Extract role entries from \\resumeSubheading blocks in EXPERIENCE section."""
    exp_section = _extract_section(tex, "EXPERIENCE")
    if not exp_section:
        return []

    # Find all resumeSubheading occurrences and extract the next 4 brace groups
    roles = []
    pos = 0
    while True:
        idx = exp_section.find("resumeSubheading", pos)
        if idx == -1:
            break
        # Find the start of the command (including backslash)
        cmd_start = idx
        # Extract brace groups after the command
        groups = _find_braced_groups(exp_section, idx + len("resumeSubheading"))
        if len(groups) >= 4:
            roles.append({
                "company_name": groups[0][2].strip(),
                "dates": groups[1][2].strip(),
                "role_title": groups[2][2].strip(),
                "location": groups[3][2].strip() or None,
            })
        pos = groups[3][1] if len(groups) >= 4 else idx + 1

    return roles


def _parse_projects(tex: str) -> list[dict[str, Any]]:
    """Extract project entries from PROJECTS section."""
    proj_section = _extract_section(tex, "PROJECTS")
    if not proj_section:
        return []

    projects = []
    pos = 0
    while True:
        idx = proj_section.find("resumeProjectHeading", pos)
        if idx == -1:
            break
        groups = _find_braced_groups(proj_section, idx + len("resumeProjectHeading"))
        if len(groups) >= 2:
            title = groups[0][2].strip()
            title = re.sub(r"\\textbf\{(.*?)\}", r"\1", title)
            projects.append({
                "title": title,
                "date_range": groups[1][2].strip(),
            })
        pos = groups[1][1] if len(groups) >= 2 else idx + 1

    # Extract Tech Stack from \resumeItem{\textbf{Tech Stack}: ...}
    tech_pattern = re.compile(
        r"\\resumeItem\{\\textbf\{Tech Stack}:\s*(.+?)\}",
        re.DOTALL,
    )
    tech_stacks = tech_pattern.findall(proj_section)

    for i, proj in enumerate(projects):
        if i < len(tech_stacks):
            proj["tech_stack_str"] = tech_stacks[i]

    return projects


def _parse_skills(tex: str) -> list[dict[str, Any]]:
    """Extract skill categories from TECHNICAL SKILLS section."""
    skills_section = _extract_section(tex, "TECHNICAL SKILLS")
    if not skills_section:
        return []

    # Match \textbf{Category} {: skill1, skill2, ...}
    pattern = re.compile(
        r"\\textbf\{([^}]+)\}\s*\{\s*:\s*([^}]+)\}",
        re.DOTALL,
    )

    result = []
    for m in pattern.finditer(skills_section):
        category = m.group(1).strip()
        skills_str = m.group(2).strip()
        skills = [s.strip() for s in skills_str.split(",") if s.strip()]
        result.append({"category": category, "skills": skills})
    return result


def _parse_certifications(tex: str) -> list[dict[str, Any]]:
    """Extract certifications from CERTIFICATIONS section."""
    cert_section = _extract_section(tex, r"CERTIFICATIONS \& PUBLICATIONS")
    if not cert_section:
        # Try without the escaped ampersand
        cert_section = _extract_section(tex, "CERTIFICATIONS \\& PUBLICATIONS")
    if not cert_section:
        return []

    # Match \textbf{Title} (year) — description. \href{url}
    pattern = re.compile(
        r"\\textbf\{([^}]+)\}\s*\((\d{4})\)"
        r"\s*(?:—\s*(.+?))?"
        r"(?:\s*\\href\{([^}]+)\})?",
        re.DOTALL,
    )

    result = []
    for m in pattern.finditer(cert_section):
        result.append({
            "title": m.group(1).strip(),
            "year": int(m.group(2)),
            "description": m.group(3).strip() if m.group(3) else None,
            "url": m.group(4) if m.group(4) else None,
        })
    return result


def _map_skill_category(label: str) -> str:
    """Map display category label to enum values."""
    mapping = {
        "Backend Development": "technical",
        "Databases": "technical",
        "Data Processing": "technical",
        "ML Algorithms & Deep Learning": "technical",
        "Gen AI & Agentic AI": "technical",
        "Cloud & MLOps": "technical",
    }
    # Strip backslashes from escaped ampersands
    clean = label.replace("\\&", "&").replace("\\", "")
    return mapping.get(clean, "technical")


async def seed(dsn: str) -> None:
    """Main seed function — idempotent, safe to run multiple times."""
    pool = DatabasePool(dsn)

    # Run migrations first
    await run_migrations(pool)

    tex = RESUME_PATH.read_text(encoding="utf-8")
    _logger.info("Parsing resume: %s (%d chars)", RESUME_PATH, len(tex))

    # ---- Skills ----
    skill_id_map: dict[str, str] = {}
    parsed_skills = _parse_skills(tex)
    _logger.info("Found %d skill categories", len(parsed_skills))

    for group in parsed_skills:
        cat = _map_skill_category(group["category"])
        for skill_name in group["skills"]:
            display = skill_name.strip()
            name = display.lower()
            # Skip already-seeded duplicates by checking DB
            existing = await pool.fetchrow(
                "SELECT id FROM skills WHERE name = $1", name
            )
            if existing:
                skill_id_map[name] = existing["id"]
                continue
            try:
                record = await create_skill(pool, name, display, cat)
                skill_id_map[name] = record["id"]
            except Exception:
                existing = await pool.fetchrow(
                    "SELECT id FROM skills WHERE name = $1", name
                )
                if existing:
                    skill_id_map[name] = existing["id"]

    _logger.info("Seeded %d skills", len(skill_id_map))

    # ---- Projects ----
    project_id_map: dict[str, str] = {}
    parsed_projects = _parse_projects(tex)
    _logger.info("Found %d projects", len(parsed_projects))

    for proj in parsed_projects:
        title = proj["title"]
        date_range = proj.get("date_range", "")
        tech_str = proj.get("tech_stack_str", "")

        # Check if already seeded
        existing = await pool.fetchrow(
            "SELECT id FROM projects WHERE title = $1 AND is_active = true", title
        )
        if existing:
            project_id_map[title] = existing["id"]
            _logger.info("  Skipped (exists): %s", title)
            continue

        # Parse date range
        start_date = None
        end_date = None
        date_match = re.match(r"(\d{4})(?:\s*--\s*(?:present|(\d{4})))?", date_range)
        if date_match:
            start_date = f"{date_match.group(1)}-01-01"
            if date_match.group(2):
                end_date = f"{date_match.group(2)}-12-31"

        # Parse tech stack
        tech_stack = [t.strip() for t in tech_str.replace("\\&", "&").split(",") if t.strip()]
        tags = tech_stack.copy()

        # Minimal description (real descriptions come from KG admin)
        desc = f"See full resume for details. Tech stack: {tech_str}" if tech_str else "Project from resume."
        if len(desc) < 50:
            desc = f"{desc} Additional details available in the knowledge graph admin panel."

        record = await create_project(
            pool,
            title=title,
            description=desc,
            tech_stack=tech_stack,
            start_date=start_date,
            end_date=end_date,
            status="completed" if end_date else "ongoing",
            tags=tags,
        )
        project_id_map[title] = record["id"]
        _logger.info("  Created: %s", title)

        # Link skills via fuzzy match
        for skill_name in tech_stack:
            name = skill_name.strip().lower()
            if name in skill_id_map:
                await link_project_skill(
                    pool, record["id"], skill_id_map[name], is_primary=True
                )
            else:
                for known_name, known_id in skill_id_map.items():
                    if name in known_name or known_name in name:
                        await link_project_skill(
                            pool, record["id"], known_id, is_primary=False
                        )
                        break

    _logger.info("Seeded %d projects", len(project_id_map))

    # ---- Roles ----
    role_id_map: dict[str, str] = {}
    parsed_roles = _parse_roles(tex)
    _logger.info("Found %d roles", len(parsed_roles))

    for role in parsed_roles:
        company_key = f"{role['company_name']}_{role['role_title']}"
        existing = await pool.fetchrow(
            "SELECT id FROM roles WHERE company_name = $1 AND role_title = $2 AND is_active = true",
            role["company_name"], role["role_title"],
        )
        if existing:
            role_id_map[company_key] = existing["id"]
            _logger.info("  Skipped (exists): %s at %s", role["role_title"], role["company_name"])
            continue

        dates = role["dates"]
        start_date = None
        end_date = None
        # Parse "Dec. 2023 -- Present" or "Mar. 2023 -- May. 2023"
        date_match = re.match(
            r"([A-Z][a-z]+\.?\s*\d{4})\s*--\s*(Present|[A-Z][a-z]+\.?\s*\d{4})",
            dates,
        )
        start_date = None
        end_date = None
        if date_match:
            try:
                from dateutil.parser import parse as parse_date
                from datetime import date as date_type
                start_dt = parse_date(date_match.group(1))
                start_date = start_dt.strftime("%Y-%m-%d") if isinstance(start_dt, date_type) else str(start_dt)[:10]
            except Exception:
                start_date = f"{date_match.group(1)[-4:]}-01-01"
            if date_match.group(2).lower() != "present":
                try:
                    end_dt = parse_date(date_match.group(2))
                    end_date = end_dt.strftime("%Y-%m-%d") if isinstance(end_dt, date_type) else str(end_dt)[:10]
                except Exception:
                    end_date = f"{date_match.group(2)[-4:]}-12-31"
        else:
            start_date = "2023-01-01"

        record = await create_role(
            pool,
            company_name=role["company_name"],
            role_title=role["role_title"],
            start_date=start_date,
            end_date=end_date,
            location=role.get("location"),
        )
        role_id_map[company_key] = record["id"]
        _logger.info("  Created: %s at %s", role["role_title"], role["company_name"])

    _logger.info("Seeded %d roles", len(role_id_map))

    # ---- Certifications ----
    certs = _parse_certifications(tex)
    _logger.info("Found %d certifications", len(certs))
    for cert in certs:
        existing = await pool.fetchrow(
            "SELECT id FROM certifications WHERE title = $1 AND year = $2 AND is_active = true",
            cert["title"], cert["year"],
        )
        if existing:
            _logger.info("  Skipped (exists): %s", cert["title"])
            continue
        await create_certification(
            pool,
            title=cert["title"],
            year=cert["year"],
            description=cert.get("description"),
            url=cert.get("url"),
        )
        _logger.info("  Created: %s", cert["title"])
    _logger.info("Seeded %d certifications", len(certs))

    await pool.close()
    _logger.info("Seed complete!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    config = get_config()
    dsn = os.getenv("DATABASE_URL", config.database_url)
    asyncio.run(seed(dsn))
