"""The mutation run: revert one fix at a time and require the smoke suite to fail.

A guard that asserts a helper the pipeline is free to ignore, or pins a constant by reading it back
from the module, passes whether or not the fix it names is in place. Seven fixes were once found
revertible with the suite green. Each entry below names a fix by the text that carries it and the
text that reverts it; the runner swaps them in, runs the suite, and puts the file back whatever
happens. Add an entry with every fix that gets a guard, and re-run:

    mutations.py                 # every entry
    mutations.py "lenient tier"  # entries whose label contains the text

Every entry must end in `suite FAILS`; an entry the runner cannot find in the file is reported as
SKIPPED, which means the fix has been rewritten and the entry needs updating.

The run mutates the working tree in place, one file at a time, for the twenty seconds each suite
run takes. It owns the tree until it finishes: nothing else may be measured against it, and nothing
may be edited in it either -- not the modules, not the Markdown. A scorer started beside it imports
whichever revert happens to be in place; an edit to a file under test is lost when the backup is
restored over it; and an edit to any other tracked file lands inside a suite run as a partial read,
because the suite reads `CHANGELOG.md`, both plugin manifests, `SKILL.md` and `AGENTS.md` as well
as the six modules reverted here. The failure that produces is indistinguishable from the one the
revert was meant to cause, which turns "this fix is unguarded" into "this fix is guarded" -- the
one conclusion this run exists to prevent. So the tracked tree is fingerprinted before the first
entry and after each one, and the run stops if anything moved.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parents[2]
SMOKE = SCRIPTS / "tests" / "run_smoke.py"
P = SCRIPTS / "pdf_references.py"
R = SCRIPTS / "reference_parser.py"
D = SCRIPTS / "dblp_check.py"
A = SCRIPTS / "audit_references.py"
T = SCRIPTS / "triage.py"
V = SCRIPTS / "verifier.py"

# (label, file, the text as fixed, the text reverted)
MUTATIONS = [
    ("extract: continuation lines opening with digits vote numeric", P,
     "        elif _NUM.match(s):             # \"12.\" / \"12  ...\" (also lineno-prefixed continuations)\n"
     "            if opens:\n                num += 1",
     "        elif _NUM.match(s):\n            num += 1"),
    ("extract: an entry needs a (year) even under a hanging indent", P,
     "        elif entry_col is not None and opens and _ENTRY_HEAD.match(s):\n            ay += 1",
     "        elif False:\n            ay += 1"),
    ("extract: _AUTHORYEAR gates entries under a hanging indent", P,
     "                starts = indent <= entry_col and bool(_ENTRY_HEAD.match(s))",
     "                starts = indent <= entry_col and bool(_AUTHORYEAR.match(s))"),
    ("extract: the right column is not aligned to the left", P,
     "    le, re_ = _text_edge(left), _text_edge(right)\n"
     "    if le is None or re_ is None or le == re_:\n        return right",
     "    return right\n    le, re_ = _text_edge(left), _text_edge(right)\n"
     "    if le is None or re_ is None or le == re_:\n        return right"),
    ("extract: the author biographies are not cut off", P,
     "    if entry_col is not None:\n        section = _hanging_block(section, entry_col)",
     "    pass"),
    ("parse: a hyphenated initial ends the author sentence", R,
     'r"(?:^|[\\s(\\[.\\-])(?:[A-Z]|proc|', 'r"(?:^|[\\s(\\[.])(?:[A-Z]|proc|'),
    ("parse: Elsevier's ', in:' venue stays in the title", R,
     '    t = _TRAILING_IN_VENUE.sub("", t)\n', ''),
    ("parse: hyphenated initials are not initials-led", R,
     '_INITIALS_LED = re.compile(r"^(?:and\\s+)?[A-Z]\\.(?:\\s*-?\\s*[A-Z]\\.)*\\s+\\S")',
     '_INITIALS_LED = re.compile(r"^(?:and\\s+)?[A-Z]\\.(?:\\s*[A-Z]\\.)*\\s+\\S")'),
    ("parse: a dotted lowercase initial is rejected", R,
     '_INITIALS_ONLY = re.compile(r"^(?=.*[A-Z])(?:[A-Z]\\.?[\\s-]*|[a-z]\\.[\\s-]*){1,4}$")',
     '_INITIALS_ONLY = re.compile(r"^(?:[A-Z]\\.?[\\s-]*){1,4}$")'),
    ("parse: `URL https://` is the identifier's label, not a title word", R,
     '(?:\\burl\\s+)?https?://', 'https?://'),
    ("parse: a ? or ! is judged on the text up to the next mark", R,
     '        nm = re.search(r"[?!](?=\\s)", nxt)\n        if nm:\n            nxt = nxt[:nm.end()]\n',
     ''),
    ("parse: the quoted opener's venue test stops at `, in:`", R,
     '_TRAILING_IN_VENUE.sub("", after[:_sentence_end(after)])', 'after[:_sentence_end(after)]'),
    ("parse: a roman numeral heading is not a sentence", R,
     'or _ROMAN_HEAD.match(text[start:m.end()].lstrip())', 'or False'),
    ("parse: the role after IEEE's names is not the title", R,
     '    rest = _LEADING_ROLE.sub("", ", ".join(fields[taken:]))',
     '    rest = ", ".join(fields[taken:])'),
    ("parse: an `et al.,` entry delimits its fields with commas", R,
     '        if m.group(0).rstrip().endswith(",") and rest[:1] not in _OPEN_Q:', '        if False:'),
    ("parse: a bare publisher field ends the title", R,
     'or _BARE_VENUE.match(tail)', 'or False'),
    ("parse: volume (issue) (year) is a venue on its own", R,
     '    if _VOLUME_ISSUE_YEAR.search(s):\n        return True\n', ''),
    ("parse: a DOI broken on its own period is rejoined", R,
     'or _continues(raw, rest.group(1))', 'or False'),
    ("parse: a two-character DOI suffix is a cut", R,
     '    if len(_doi_suffix(doi)) <= 2:\n        return True\n', ''),
    ("dblp: the edition suffix stays on the record", D,
     '    candidate = _EDITION_SUFFIX.sub("", candidate or "")\n', ''),
    ("dblp: a parenthesised alias stays in the name", D,
     '    tokens = re.split(r"[\\s.,]+", name.replace("(", " ").replace(")", " "))',
     '    tokens = re.split(r"[\\s.,]+", name)'),
    ("dblp: no leave-a-pair-out retrieval fallback", D,
     "            for q in _glued_query(title) + _dropped_pair_queries(title):",
     "            for q in _glued_query(title):"),
    ("dblp: the lenient tier is a wildcard", D,
     "    return matched >= 1 or not _lists_people(candidate)", "    return True"),
    ("dblp: an umlaut does not read as its transliteration", D,
     "    if _UMLAUT.search(composed):", "    if False:"),
    ("dblp: the nearest title needs no cited person on it", D,
     '        if authors_match(list(authors), candidate["authors"], record_complete=True):',
     "        if True:"),
    ("dblp: the nearest title may be three word edits away", D,
     "_NEAREST_EDITS = 2", "_NEAREST_EDITS = 3"),
    ("dblp: the cited DOI does not choose among shared-title records", D,
     "                            not doi_match(c, dois),\n", ""),
    ("dblp: the cited page range does not choose among shared-title records", D,
     "                            not pages_match(c, raw),\n", ""),
    ("dblp: the cited volume does not choose among shared-title records", D,
     "                            not volume_match(c, raw),\n", ""),
    ("dblp: the year is read before the locator the citation prints", D,
     "                            not doi_match(c, dois),\n"
     "                            not pages_match(c, raw),\n"
     "                            not volume_match(c, raw),\n"
     "                            str(c.year) not in years))",
     "                            str(c.year) not in years,\n"
     "                            not doi_match(c, dois),\n"
     "                            not pages_match(c, raw),\n"
     "                            not volume_match(c, raw)))"),
    ("dblp: the year the citation prints does not choose among shared-title records", D,
     "                            str(c.year) not in years))",
     "                            False))"),
    ("dblp: the preprint may come before the published record", D,
     '    out.sort(key=lambda c: ((c.venue or "").strip().lower() == "corr",\n',
     "    out.sort(key=lambda c: (False,\n"),
    ("dblp: the locator outranks the published record", D,
     '    out.sort(key=lambda c: ((c.venue or "").strip().lower() == "corr",\n'
     "                            not doi_match(c, dois),",
     "    out.sort(key=lambda c: (not doi_match(c, dois),\n"
     '                            (c.venue or "").strip().lower() == "corr",'),
    ("verifier: the citation's years never reach the mirror", V,
     '        candidates = title_candidates(self.dblp_path, title, cited_years(raw), raw,\n'
     '                                      getattr(ref, "doi", None))',
     "        candidates = title_candidates(self.dblp_path, title)"),
    ("verifier: the citation's text and DOI never reach the mirror", V,
     '        candidates = title_candidates(self.dblp_path, title, cited_years(raw), raw,\n'
     '                                      getattr(ref, "doi", None))',
     "        candidates = title_candidates(self.dblp_path, title, cited_years(raw))"),
    ("triage: authors_absent is not read off the matched record", T,
     '    return absent_authors((ref.get("parsed") or {}).get("authors") or [], dv["found_authors"])',
     '    return []'),
    ("audit: the nearest title is asked for whatever the mirror said", A,
     '        if any(r.get("db") == DBLP and r.get("status") == NO_MATCH\n'
     '               for r in v.get("db_results") or []):',
     "        if True:"),
    ("triage: a skipped backend is not reported as never asked", T,
     '            if r.get("status") == "skipped"]', "            if False]"),
    ("triage: every resolved title reads as the cited one", T,
     '                    "cited_title": titles_match(cited, title) if title else None})',
     '                    "cited_title": True if title else None})'),
]


def _tracked_fingerprint() -> dict[str, str]:
    """A content hash of every tracked file, to catch a tree edited while the run is in flight.

    Tracked only, so the `.mutbak` backup written beside each file under test does not register as
    a change of its own. Outside a git checkout there is nothing to list and the check is vacuous,
    which is the right answer for a plugin install: this is a development tool."""
    try:
        listing = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                                 capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    out: dict[str, str] = {}
    for rel in listing.split("\0"):
        if not rel:
            continue
        try:
            out[rel] = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()
        except OSError:
            out[rel] = "missing"
    return out


def main() -> int:
    only = sys.argv[1:]
    bad = 0
    base = _tracked_fingerprint()
    for label, path, fixed, reverted in MUTATIONS:
        if only and not any(o in label for o in only):
            continue
        src = path.read_text(encoding="utf-8")
        if src.count(fixed) != 1:
            print(f"{label:60s} -> SKIPPED: the fixed text occurs {src.count(fixed)} times")
            bad += 1
            continue
        backup = path.with_suffix(path.suffix + ".mutbak")
        shutil.copy(path, backup)
        try:
            path.write_text(src.replace(fixed, reverted), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(SMOKE)], capture_output=True, text=True)
            failed = [l.strip() for l in proc.stdout.splitlines() if l.strip().startswith("FAIL")]
        finally:
            shutil.move(backup, path)
        now = _tracked_fingerprint()
        moved = sorted(k for k in set(base) | set(now) if base.get(k) != now.get(k))
        if moved:
            print(f"\nSTOPPED after {label!r}: the tree changed under the run "
                  f"({', '.join(moved[:5])}). Every result so far was measured against a tree that "
                  "moved, so none of them is evidence. Freeze the tree and start again.")
            return 1
        if proc.returncode != 0:
            print(f"{label:60s} -> suite FAILS ({len(failed)} check(s)): {failed[0][:110] if failed else ''}")
        else:
            print(f"{label:60s} -> suite PASSES: the fix is revertible, add a guard")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
