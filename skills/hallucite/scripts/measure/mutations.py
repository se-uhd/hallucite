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
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
SMOKE = SCRIPTS / "tests" / "run_smoke.py"
P = SCRIPTS / "pdf_references.py"
R = SCRIPTS / "reference_parser.py"
D = SCRIPTS / "dblp_check.py"

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
]


def main() -> int:
    only = sys.argv[1:]
    bad = 0
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
        if proc.returncode != 0:
            print(f"{label:60s} -> suite FAILS ({len(failed)} check(s)): {failed[0][:110] if failed else ''}")
        else:
            print(f"{label:60s} -> suite PASSES: the fix is revertible, add a guard")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
