"""schema_checks.py - hallucite schema rules consumed by lint_markdown.py.

One check, against the skill manifest `SKILL.md`: the agentskills.io frontmatter
constraint PyMarkdown does not know about - the `name` field must be present,
<=64 chars, lowercase letters/digits/hyphens (no leading, trailing, or doubled
hyphen), and must match the skill's directory name.

The linter (`lint_markdown.py`, synced from pymarkdown-skill) loads this file via
importlib and calls `schema_findings(text, path)` at lint time.
"""
import re

SKILL_NAME = "hallucite"

_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_NAME_FIELD_RE = re.compile(r"name:\s*(\S+)\s*$")


def _frontmatter_name(text):
    """The top-level `name:` scalar from the leading `---` frontmatter, or None."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = _NAME_FIELD_RE.match(line)
        if m:
            return m.group(1)
    return None


def schema_findings(text, path):
    if path.name != "SKILL.md":
        return []
    name = _frontmatter_name(text)
    if name is None:
        return [(1, "skill-name-missing", "SKILL.md frontmatter has no top-level `name`")]
    findings = []
    if len(name) > 64:
        findings.append((1, "skill-name-too-long", f"`name` is {len(name)} chars (max 64)"))
    if not _NAME_RE.match(name):
        findings.append((1, "skill-name-format",
                         "`name` must be lowercase a-z/0-9/hyphen, no leading, trailing, or doubled hyphen"))
    if name != path.parent.name:
        findings.append((1, "skill-name-mismatch",
                         f"`name` ({name}) must match the skill directory ({path.parent.name})"))
    return findings
