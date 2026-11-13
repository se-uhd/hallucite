#!/usr/bin/env python3
"""opencode_index.py [--check] [<path-to-index.json>]

Write (or verify) the OpenCode HTTP-catalog manifest `skills/index.json`, the
OpenCode counterpart of the Claude Code and Codex plugin manifests. A user
points `skills` in `opencode.json(c)` at
`https://raw.githubusercontent.com/se-uhd/hallucite/main/skills/` and OpenCode
downloads each listed file from `<base-url>/hallucite/<file>` into its skill
cache, so the list must name every file an installed copy needs, explicitly --
the catalog format has no directories or globs, only files.

The list is derived from the skill tree, never maintained by hand: everything
under `skills/hallucite/` ships except the development-only tools (the test
suite, the measurement harness, the vendor refresher and its bookkeeping,
recordings tooling, and this generator itself) and build artifacts. The
vendored linter and its licenses ship, because an installed copy runs
`triage report`'s lint step.

The entry version is read from `.claude-plugin/plugin.json`, the version the
smoke suite already holds in sync across both plugin manifests, SKILL.md and
the CHANGELOG. OpenCode re-downloads a catalog skill only when the entry's
version changes, so this file's version must move with every release.

With `--check`, verify the file on disk instead of writing it: same list, same
version, valid shape, every listed path safe and present. The smoke suite's
packaging tier runs exactly that.

Exit codes
----------
  0  index written, or verified with `--check`.
  1  `--check` and the index on disk disagrees with the derived list or the
     manifest version.
  2  could not read the skill tree, the manifest, or the index; or the index
     has the wrong structure.
"""
import argparse
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent          # skills/hallucite
SKILLS_ROOT = SKILL_DIR.parent          # skills/ -- also where index.json lives
REPO = SKILLS_ROOT.parent

# Development-only trees and files that no installed copy needs. Everything
# else under skills/hallucite/ ships, including scripts/_vendor/ and
# scripts/bundled_licenses/ (the linter an installed triage report runs, and
# the licenses that must travel with vendored code).
EXCLUDE_DIRS = {"__pycache__", "tests", "measure"}
EXCLUDE_FILES = {
    "refresh_vendor.py",        # maintainer-only vendor refresher
    "verification_results.py",  # measurement recordings tooling
    "opencode_index.py",        # this generator
    ".pymarkdown-skill-version",  # vendor refresher bookkeeping
}


def version_from_manifest() -> str:
    manifest = REPO / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"opencode_index.py: cannot read {manifest}: {e}\n")
        raise SystemExit(2)
    if not isinstance(version, str) or not version.strip():
        sys.stderr.write(f"opencode_index.py: {manifest} has no version\n")
        raise SystemExit(2)
    return version


def derived_files() -> list[str]:
    """The skill tree, relative to it, as the catalog's `files` list."""
    files = []
    for path in sorted(SKILL_DIR.rglob("*")):
        rel = path.relative_to(SKILL_DIR).as_posix()
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.is_dir():
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if not path.is_file():
            continue
        files.append(rel)
    return files


def unsafe(path: str) -> str | None:
    """Why a path cannot travel as a catalog `files` entry, or None if it can.
    Mirrors what the OpenCode catalog downloader accepts: relative POSIX paths
    with no `..`, no backslash, and no URL-significant characters."""
    if not path or path.startswith("/") or path.endswith("/"):
        return "not a relative file path"
    if "\\" in path or any(c in path for c in "?#"):
        return "contains a character catalogs cannot carry"
    if any(part in ("", ".", "..") for part in path.split("/")):
        return "has an empty or dot segment"
    return None


def build_index() -> dict:
    return {"skills": [{
        "name": "hallucite",
        "version": version_from_manifest(),
        "files": derived_files(),
    }]}


def validate(index, origin: Path) -> list[str]:
    """Structural problems in a parsed index, independent of the derivation."""
    problems = []
    if not isinstance(index, dict) or not isinstance(index.get("skills"), list):
        return [f"{origin}: top level must be an object with a `skills` array"]
    for entry in index["skills"]:
        if not isinstance(entry, dict):
            problems.append(f"{origin}: each skills entry must be an object")
            continue
        name = entry.get("name")
        files = entry.get("files")
        if not isinstance(name, str) or not name:
            problems.append(f"{origin}: entry without a `name`")
        if not isinstance(files, list) or not files:
            problems.append(f"{origin}: entry `{name}` has no `files` array")
            continue
        if "SKILL.md" not in files and f"{name}.md" not in files:
            problems.append(f"{origin}: entry `{name}` lists neither SKILL.md nor {name}.md")
        if "scripts/run.sh" not in files:
            problems.append(f"{origin}: entry `{name}` does not list scripts/run.sh")
        for f in files:
            if not isinstance(f, str):
                problems.append(f"{origin}: non-string file entry {f!r}")
            elif (why := unsafe(f)) is not None:
                problems.append(f"{origin}: {f!r} {why}")
            elif not (SKILL_DIR / f).is_file():
                problems.append(f"{origin}: {f} does not exist in the skill tree")
    return problems


def check(index_path: Path) -> int:
    try:
        on_disk = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"opencode_index.py: cannot read {index_path}: {e}\n")
        return 2
    problems = validate(on_disk, index_path)
    if problems:
        for p in problems:
            sys.stderr.write(f"catalog mismatch: {p}\n")
        return 1

    entry = on_disk["skills"][0]
    want = build_index()
    if entry.get("version") != want["skills"][0]["version"]:
        sys.stderr.write(
            "catalog mismatch: entry version "
            f"{entry.get('version')!r} != manifest version "
            f"{want['skills'][0]['version']!r} (.claude-plugin/plugin.json)\n")
        return 1
    if entry.get("files") != want["skills"][0]["files"]:
        on_set, want_set = set(entry["files"]), set(want["skills"][0]["files"])
        for f in sorted(want_set - on_set):
            sys.stderr.write(f"catalog mismatch: missing from index: {f}\n")
        for f in sorted(on_set - want_set):
            sys.stderr.write(f"catalog mismatch: listed but excluded: {f}\n")
        if on_set == want_set:
            sys.stderr.write("catalog mismatch: file order differs from the derivation\n")
        return 1
    sys.stderr.write(f"catalog ok: {index_path}\n")
    return 0


def write(index_path: Path) -> int:
    index = build_index()
    problems = validate(index, Path("<derived>"))
    if problems:
        for p in problems:
            sys.stderr.write(f"opencode_index.py: {p}\n")
        return 2
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    sys.stderr.write(f"wrote {index_path} ({len(index['skills'][0]['files'])} files, "
                     f"version {index['skills'][0]['version']})\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Write or verify the OpenCode catalog manifest "
                     "skills/index.json from the skill tree."))
    parser.add_argument("--check", action="store_true",
                        help="verify the index on disk instead of writing it")
    parser.add_argument("index_path", nargs="?", metavar="index.json",
                        help=("manifest to write or check (defaults to "
                              "skills/index.json beside the skill)"))
    args = parser.parse_args()
    target = (Path(args.index_path) if args.index_path
              else SKILLS_ROOT / "index.json")
    return check(target) if args.check else write(target)


if __name__ == "__main__":
    sys.exit(main())
