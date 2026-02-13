"""
Skills loader — AgentSkills-compatible prompt management.

Inspired by OpenClaw's SKILL.md pattern, this module loads AI prompt
"skills" from markdown files with YAML frontmatter. Each skill teaches
the AI assistant how to handle a specific domain (renovation stages,
budget analysis, report generation, etc.).

Instead of hardcoding prompts in Python, skills are defined as markdown
files that can be:
  - Edited by admins without touching code
  - Hot-reloaded at runtime (when the watcher is enabled)
  - Extended with user-defined or community skills

Skill format (SKILL.md):
    ---
    name: budget-analysis
    description: Analyze renovation project budgets
    priority: 10
    ---
    You are a budget analyst for renovation projects...

Directory precedence (highest wins):
  1. Workspace skills: <skills_dir>/
  2. Built-in skills: src/bot/skills/

Usage:
    from bot.services.skills_loader import get_all_skills, get_skill_prompt
    skills = get_all_skills()
    prompt = get_skill_prompt("rag-assistant")
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Module-level skill registry
_skills: dict[str, "Skill"] = {}
_loaded = False


@dataclass
class Skill:
    """
    A loaded skill definition.

    Mirrors OpenClaw's AgentSkills format:
      - name: unique identifier
      - description: short description for token-efficient listing
      - instructions: full prompt text (the body of SKILL.md)
      - priority: load order (higher = loaded later, overrides earlier)
      - metadata: optional extra fields from frontmatter
      - source_path: where this skill was loaded from
    """
    name: str
    description: str = ""
    instructions: str = ""
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, priority={self.priority}, source={self.source_path!r})"


# ── YAML frontmatter parser ──────────────────────────────────

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)$",
    re.DOTALL,
)


def parse_skill_file(path: Path) -> Skill | None:
    """
    Parse a SKILL.md file into a Skill object.

    Expected format:
        ---
        name: skill-name
        description: What the skill does
        priority: 10
        metadata:
          requires_ai: true
        ---
        Full instructions for the AI go here.
        Multiple lines supported with Markdown formatting.

    Returns None if the file cannot be parsed.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Cannot read skill file %s: %s", path, e)
        return None

    match = _FRONTMATTER_RE.match(text)
    if not match:
        logger.warning("No YAML frontmatter in %s", path)
        return None

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    try:
        fm = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", path, e)
        return None

    name = fm.get("name")
    if not name:
        logger.warning("Skill in %s has no 'name' field", path)
        return None

    return Skill(
        name=name,
        description=fm.get("description", ""),
        instructions=body,
        priority=int(fm.get("priority", 0)),
        metadata=fm.get("metadata", {}),
        source_path=str(path),
    )


# ── Directory scanning ────────────────────────────────────────


def _discover_skill_files(directory: Path) -> list[Path]:
    """Find all SKILL.md files in a directory (recursive)."""
    if not directory.is_dir():
        return []

    results: list[Path] = []
    for skill_file in directory.rglob("SKILL.md"):
        results.append(skill_file)

    return sorted(results)


def _get_skill_directories() -> list[Path]:
    """
    Return skill directories in precedence order (lowest first).

    1. Built-in skills: src/bot/skills/  (shipped with the project)
    2. Custom skills: SKILLS_DIR from config (user-defined overrides)
    """
    from bot.config import settings

    dirs: list[Path] = []

    # Built-in skills directory
    builtin_dir = Path(__file__).parent.parent / "skills"
    if builtin_dir.is_dir():
        dirs.append(builtin_dir)

    # Project root skills/ fallback
    project_root = Path(__file__).parent.parent.parent.parent
    root_skills = project_root / "skills"
    if root_skills.is_dir() and root_skills != builtin_dir:
        dirs.append(root_skills)

    # Custom skills directory from config
    if settings.skills_dir:
        custom = Path(settings.skills_dir)
        if custom.is_dir() and custom not in dirs:
            dirs.append(custom)

    return dirs


# ── Public API ───────────────────────────────────────────────


def load_skills(force: bool = False) -> dict[str, Skill]:
    """
    Load all skills from all skill directories.

    Skills are loaded in precedence order — later directories
    override earlier ones (same name). Within a directory,
    higher priority wins.

    Args:
        force: reload even if already loaded.

    Returns:
        Dict of name → Skill.
    """
    global _skills, _loaded

    if _loaded and not force:
        return _skills

    all_skills: dict[str, Skill] = {}
    dirs = _get_skill_directories()

    for skill_dir in dirs:
        files = _discover_skill_files(skill_dir)
        for skill_file in files:
            skill = parse_skill_file(skill_file)
            if skill is None:
                continue

            existing = all_skills.get(skill.name)
            if existing and existing.priority > skill.priority:
                logger.debug(
                    "Skipping %s from %s (lower priority than %s)",
                    skill.name, skill.source_path, existing.source_path,
                )
                continue

            all_skills[skill.name] = skill
            logger.debug("Loaded skill: %s from %s", skill.name, skill.source_path)

    _skills = all_skills
    _loaded = True

    logger.info(
        "Skills loaded: %d skills from %d directories",
        len(_skills), len(dirs),
    )
    for skill in sorted(_skills.values(), key=lambda s: s.priority):
        logger.debug("  [%d] %s — %s", skill.priority, skill.name, skill.description)

    return _skills


def get_all_skills() -> dict[str, Skill]:
    """Get all loaded skills (loads on first call)."""
    if not _loaded:
        load_skills()
    return _skills


def get_skill(name: str) -> Skill | None:
    """Get a skill by name."""
    skills = get_all_skills()
    return skills.get(name)


def get_skill_prompt(name: str) -> str | None:
    """Get just the instruction text of a skill by name."""
    skill = get_skill(name)
    return skill.instructions if skill else None


def get_combined_system_prompt(*skill_names: str) -> str:
    """
    Combine multiple skill prompts into a single system prompt.

    Skills are joined with section separators. Missing skills are skipped.

    Example:
        prompt = get_combined_system_prompt("rag-assistant", "budget-analysis")
    """
    parts: list[str] = []
    for name in skill_names:
        skill = get_skill(name)
        if skill:
            parts.append(f"=== {skill.description or skill.name} ===\n{skill.instructions}")
        else:
            logger.warning("Skill '%s' not found", name)

    return "\n\n".join(parts)


def format_skills_for_prompt() -> str:
    """
    Format all loaded skills into an XML listing for the system prompt.

    Mirrors OpenClaw's formatSkillsForPrompt — a token-efficient listing
    of available skills injected into the model context.

    Returns:
        XML string listing all skills (or empty string if none loaded).
    """
    skills = get_all_skills()
    if not skills:
        return ""

    parts = ["<available_skills>"]
    for skill in sorted(skills.values(), key=lambda s: (s.priority, s.name)):
        name_esc = skill.name.replace("&", "&amp;").replace("<", "&lt;")
        desc_esc = skill.description.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(
            f"  <skill><name>{name_esc}</name>"
            f"<description>{desc_esc}</description></skill>"
        )
    parts.append("</available_skills>")

    return "\n".join(parts)


def reload_skills() -> dict[str, Skill]:
    """Force-reload all skills (useful for hot-reload or testing)."""
    return load_skills(force=True)
