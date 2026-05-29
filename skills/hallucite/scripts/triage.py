#!/usr/bin/env python3
"""Stage 3 helper: turn the database-verification output into a triage worklist,
and assemble the final reports once triage verdicts exist.

The web searching itself is done by the interactive LLM agent, not this script. The flow is:

    python triage.py worklist [--pending]   # -> out/triage_worklist.json (what to check)
    python triage.py status                 # per-paper done / pending counts
    # ... the agent investigates each entry and records verdicts in
    #     out/triage_verdicts.json  as  {"<paper_id>:<number>": {category, finding}} ...
    python triage.py report                 # -> out/reports/*.md

Stage 3 can run on papers already finished by Stages 1+2 while the audit keeps going:
worklist/report read each per-paper JSON the audit has written, and verdicts accumulate
per `<paper_id>:<number>`, so `worklist --pending` surfaces only newly-finished work.

A reference needs triage when its db_verification.status is not "verified".

Verdict categories (severity):
    real-published / real-grey-literature / real-preprint-or-unpublished   (low)
    partial-match        (title close, but author/year/venue off: a citation error)  (medium)
    likely-hallucinated  (no matching record found)                                  (high)
    unclear              (no confident verdict; leave for a human)                    (-)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

FLAG_CATEGORIES = ("likely-hallucinated", "partial-match", "unclear")
SEVERITY = {
    "real-published": "low", "real-grey-literature": "low",
    "real-preprint-or-unpublished": "low", "partial-match": "medium",
    "likely-hallucinated": "high", "unclear": "-",
}


_NON_PAPER_JSON = {"summary.json", "triage_worklist.json", "triage_verdicts.json"}


def _natural_key(name: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + os.replace so a concurrent reader never sees a partial file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _load_verdicts(out_dir: Path) -> dict:
    path = out_dir / "triage_verdicts.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_papers(out_dir: Path) -> list[dict]:
    """Per-paper JSON records in out_dir (any filename), naturally sorted. The
    pipeline's own outputs (summary / worklist / verdicts) are excluded."""
    files = [f for f in out_dir.glob("*.json") if f.name not in _NON_PAPER_JSON]
    return [json.loads(f.read_text()) for f in sorted(files, key=lambda f: _natural_key(f.name))]


def is_retracted(ref: dict) -> bool:
    return bool((ref.get("db_verification") or {}).get("retraction_info"))


def needs_triage(ref: dict) -> bool:
    # Needs triage iff the validator checked the reference (db_verification present) but did not
    # confirm it. Defined by negation of "verified" rather than a hard-coded list of failure
    # statuses, so a status such as hallucinator's "mismatch" can no longer fall through the list
    # and be silently dropped from the worklist and the report.
    dv = ref.get("db_verification")
    return dv is not None and dv.get("status") != "verified"


def cmd_worklist(out_dir: Path, pending: bool = False) -> None:
    recorded = _load_verdicts(out_dir) if pending else {}
    items = []
    for paper in load_papers(out_dir):
        for ref in paper["references"]:
            if not needs_triage(ref):
                continue
            if pending and f"{paper['paper_id']}:{ref['original_number']}" in recorded:
                continue
            dv = ref["db_verification"]
            p = ref.get("parsed") or {}
            items.append({
                "paper_id": paper["paper_id"],
                "number": ref["original_number"],
                "status": dv["status"],
                "title": p.get("title"),
                "authors": p.get("authors", []),
                "doi": p.get("doi"),
                "arxiv_id": p.get("arxiv_id"),
                "failed_dbs": dv.get("failed_dbs", []),
                "raw_citation": ref["raw_citation"],
            })
    dest = out_dir / "triage_worklist.json"
    _atomic_write(dest, json.dumps(items, indent=2, ensure_ascii=False))
    by_paper: dict[str, int] = {}
    for it in items:
        by_paper[it["paper_id"]] = by_paper.get(it["paper_id"], 0) + 1
    label = "pending " if pending else ""
    print(f"{len(items)} {label}references need triage across {len(by_paper)} papers "
          f"-> {dest}")
    for pid, n in sorted(by_paper.items(), key=lambda kv: _natural_key(kv[0])):
        print(f"  {pid}: {n}")


def _verify_sheet(paper: dict, items: list) -> str:
    """A manual-verification checklist for one paper's flagged references, with one-click
    search links so a human can confirm or refute each quickly."""
    def q(s: str) -> str:
        return urllib.parse.quote(s or "")
    lines = [f"# Manual verification: {paper['paper_id']}", "",
             f"- PDF: `{paper['pdf_path']}`",
             f"- {len(items)} reference(s) need a human check. Fill in each **Verdict** line.", ""]
    for ref, v in sorted(items, key=lambda x: ref_num(x[0])):
        p = ref.get("parsed") or {}
        title = p.get("title") or ""
        query = title or ref["raw_citation"][:120]
        links = [f"[Scholar](https://scholar.google.com/scholar?q={q(query)})",
                 f"[Google](https://www.google.com/search?q={q(query)})"]
        if p.get("doi"):
            links.append(f"[DOI](https://doi.org/{p['doi']})")
        if p.get("arxiv_id"):
            links.append(f"[arXiv](https://arxiv.org/abs/{p['arxiv_id']})")
        lines += [
            f"## [{ref['original_number']}] {v['category']} (severity {SEVERITY.get(v['category'], '-')})",
            "",
            f"- **Verdict:** ____  (real / hallucinated / citation-error)",
            f"- Title: {title or '(not parsed)'}",
            f"- Authors: {', '.join(p.get('authors') or []) or '(not parsed)'}"
            + (f" · DOI: {p['doi']}" if p.get('doi') else "")
            + (f" · arXiv: {p['arxiv_id']}" if p.get('arxiv_id') else ""),
            f"- Raw citation: {ref['raw_citation']}",
            f"- Automated finding: {v.get('finding', '')}",
            f"- Search: " + " · ".join(links),
            "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _lint_reports(paths):
    """Auto-fix each generated report in place with the co-located Markdown linter, so the
    files this tool writes are valid Markdown by default. Best-effort: returns None (skips)
    if the vendored lint_markdown.py is not present next to this script."""
    linter = Path(__file__).resolve().parent / "lint_markdown.py"
    if not linter.is_file():
        return None
    clean = 0
    for p in paths:
        r = subprocess.run([sys.executable, str(linter), "--fix", str(p)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            clean += 1
        elif r.stdout:
            sys.stderr.write(r.stdout)
    return clean, len(paths)


def cmd_report(out_dir: Path) -> None:
    reports = out_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    verdicts = _load_verdicts(out_dir)

    flagged: list[tuple[dict, dict, dict]] = []  # (paper, ref, verdict)
    written: list = []
    today = dt.date.today().isoformat()

    for paper in load_papers(out_dir):
        pid = paper["paper_id"]
        verified = [r for r in paper["references"]
                    if (r.get("db_verification") or {}).get("status") == "verified"]
        triage = [r for r in paper["references"] if needs_triage(r)]
        retracted = [r for r in paper["references"] if is_retracted(r)]

        lines = [f"# Reference check: {pid}", "",
                 f"- PDF: `{paper['pdf_path']}`",
                 f"- References: {paper['num_references']}",
                 f"- Verified by database: {len(verified)}",
                 f"- Needs triage (not in any database): {len(triage)}"]
        if retracted:
            lines.append(f"- **RETRACTED: {len(retracted)}**")
        lines.append("")

        if triage:
            lines += ["## Triage", ""]
            for r in triage:
                v = verdicts.get(f"{pid}:{r['original_number']}")
                cat = v["category"] if v else "(pending)"
                sev = SEVERITY.get(cat, "-")
                htitle = ((r["parsed"] or {}).get("title") or r["raw_citation"][:70]).rstrip(" .,;:!?")
                lines.append(f"### [{r['original_number']}] {htitle}")
                lines.append("")
                lines.append(f"- Raw: {r['raw_citation']}")
                lines.append(f"- DB status: {r['db_verification']['status']}")
                lines.append(f"- Category: **{cat}** (severity: {sev})")
                if v and v.get("finding"):
                    lines.append(f"- Finding: {v['finding']}")
                lines.append("")
                if v and cat in FLAG_CATEGORIES:
                    flagged.append((paper, r, v))

        report_path = reports / f"reference-check-{pid}.md"
        _atomic_write(report_path, "\n".join(lines).rstrip("\n") + "\n")
        written.append(report_path)

    # Corpus rollup for human review.
    roll = ["# Potentially hallucinated references", "",
            f"Generated: {today}", ""]
    if not flagged:
        roll.append("No references were flagged as likely-hallucinated, partial-match, or unclear.")
    else:
        # Group by paper; rank papers by their count of high-severity (likely-hallucinated) flags.
        by_paper: dict[str, list] = {}
        for paper, ref, v in flagged:
            by_paper.setdefault(paper["paper_id"], []).append((paper, ref, v))

        def sev_counts(items):
            c = {"high": 0, "medium": 0, "other": 0}
            for _, _, v in items:
                s = SEVERITY.get(v["category"], "-")
                c["high" if s == "high" else "medium" if s == "medium" else "other"] += 1
            return c

        ranked = sorted(by_paper.items(),
                        key=lambda kv: (-sev_counts(kv[1])["high"], -len(kv[1]), kv[0]))

        hi = sum(1 for _, _, v in flagged if SEVERITY.get(v["category"]) == "high")
        med = sum(1 for _, _, v in flagged if SEVERITY.get(v["category"]) == "medium")
        roll += [f"**{len(flagged)} references flagged** for human review across "
                 f"{len(by_paper)} papers: **{hi} likely-hallucinated**, {med} partial-match "
                 f"(citation errors), {len(flagged) - hi - med} unclear.", "",
                 "| Paper | likely-hallucinated | partial-match | unclear |",
                 "|---|---|---|---|"]
        for pid, items in ranked:
            c = sev_counts(items)
            roll.append(f"| {pid} | {c['high']} | {c['medium']} | {c['other']} |")
        roll.append("")

        for pid, items in ranked:
            roll.append(f"## {pid}")
            roll.append("")
            for paper, ref, v in sorted(items, key=lambda x: ref_num(x[1])):
                title = (ref["parsed"] or {}).get("title") or ""
                roll.append(f"- **[{ref['original_number']}] {v['category']}** "
                            f"(severity {SEVERITY.get(v['category'], '-')}): {title}")
                roll.append(f"  - Raw: {ref['raw_citation']}")
                roll.append(f"  - Finding: {v.get('finding', '')}")
            roll.append("")
    rollup_path = reports / "potential-hallucinations.md"
    _atomic_write(rollup_path, "\n".join(roll).rstrip("\n") + "\n")
    written.append(rollup_path)

    # One manual-verification sheet per paper that has flagged references.
    vby: dict = {}
    for paper, ref, v in flagged:
        vby.setdefault(paper["paper_id"], (paper, []))[1].append((ref, v))
    for pid, (paper, its) in vby.items():
        verify_path = reports / f"verify-{pid}.md"
        _atomic_write(verify_path, _verify_sheet(paper, its))
        written.append(verify_path)

    lint_summary = _lint_reports(written)
    print(f"Wrote to {reports}/: per-paper reference-check reports, "
          f"potential-hallucinations.md, and {len(vby)} verify-*.md sheets ({len(flagged)} flagged).")
    if lint_summary is not None:
        clean, total = lint_summary
        suffix = "" if clean == total else " (residual findings above)"
        print(f"Markdown lint: {clean}/{total} report(s) clean{suffix}")


def ref_num(ref: dict) -> int:
    return ref["original_number"]


def cmd_record(out_dir: Path, paper_id: str, number: str, category: str, finding: str) -> None:
    if category not in SEVERITY:
        raise SystemExit(f"unknown category {category!r}; expected one of {sorted(SEVERITY)}")
    # Surface typo'd keys: a verdict whose paper_id:number matches no audited reference would
    # otherwise sit in triage_verdicts.json forever and never appear in any report.
    known = {f"{p['paper_id']}:{r['original_number']}"
             for p in load_papers(out_dir) for r in p["references"]}
    if known and f"{paper_id}:{number}" not in known:
        print(f"warning: {paper_id}:{number} matches no reference in {out_dir}/ -- recording it "
              f"anyway, but it will not appear in any report; re-check the paper_id and number.",
              file=sys.stderr)
    path = out_dir / "triage_verdicts.json"
    data = _load_verdicts(out_dir)
    data[f"{paper_id}:{number}"] = {"category": category, "finding": finding}
    _atomic_write(path, json.dumps(data, indent=2, ensure_ascii=False))
    print(f"recorded {paper_id}:{number} = {category} ({len(data)} verdicts total)")


def cmd_status(out_dir: Path) -> None:
    recorded = _load_verdicts(out_dir)
    rows = []
    for paper in load_papers(out_dir):
        pid = paper["paper_id"]
        needs = [r for r in paper["references"] if needs_triage(r)]
        done = sum(1 for r in needs if f"{pid}:{r['original_number']}" in recorded)
        rows.append((pid, paper["num_references"], len(needs), done, len(needs) - done))
    print(f"{'paper':<28}{'refs':>6}{'needs':>7}{'done':>6}{'pending':>9}")
    for pid, refs, needs, done, pend in sorted(rows, key=lambda r: _natural_key(r[0])):
        mark = "  complete" if needs and pend == 0 else ""
        print(f"{pid:<28}{refs:>6}{needs:>7}{done:>6}{pend:>9}{mark}")
    tn = sum(r[2] for r in rows)
    td = sum(r[3] for r in rows)
    print(f"\n{len(rows)} papers | needs review: {tn} | recorded: {td} | pending: {tn - td}")


def main() -> int:
    p = argparse.ArgumentParser(description="Stage 3 triage worklist / status / record / report.")
    sub = p.add_subparsers(dest="command", required=True)
    wl = sub.add_parser("worklist")
    wl.add_argument("--out", default="out")
    wl.add_argument("--pending", action="store_true",
                    help="only references not already recorded in triage_verdicts.json")
    sub.add_parser("status").add_argument("--out", default="out")
    sub.add_parser("report").add_argument("--out", default="out")
    rec = sub.add_parser("record")
    rec.add_argument("paper_id")
    rec.add_argument("number")
    rec.add_argument("category")
    rec.add_argument("finding")
    rec.add_argument("--out", default="out")
    args = p.parse_args()
    out = Path(args.out)
    if args.command == "worklist":
        cmd_worklist(out, pending=args.pending)
    elif args.command == "status":
        cmd_status(out)
    elif args.command == "report":
        cmd_report(out)
    else:
        cmd_record(out, args.paper_id, args.number, args.category, args.finding)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
