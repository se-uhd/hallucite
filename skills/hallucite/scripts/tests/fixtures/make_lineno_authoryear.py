#!/usr/bin/env python3
"""Generate the `lineno` + author-year extraction fixture (PDF and its text shape).

    python skills/hallucite/scripts/tests/fixtures/make_lineno_authoryear.py

Writes `lineno_authoryear.pdf` and `lineno_authoryear.txt` next to this script. Only the PDF is
used by the smoke tests; the .txt is committed alongside it so the intended layout is reviewable
without a PDF reader.

Every author, title, venue, year, and DOI below is invented. The fixture reproduces the *layout*
of a Springer-style journal submission that extraction once mangled -- not its content -- so the
regression can be tested without redistributing anyone's manuscript.

The layout traps it reproduces, all of which occurred together in the reported paper:

  * LaTeX `lineno` margin numbers in BOTH renderings `pdftotext -layout` produces -- alone on
    their own line, and inline in the gutter before the text -- switching between them mid-page.
  * A hanging-indent author-year bibliography: entries at one column, continuations deeper.
    Author-year entries carry no label, so this indent is the only entry delimiter.
  * Margin numbers that reset on every page.
  * A wrapped author list whose `(year)` falls on the *continuation* line, which itself opens
    with a surname and initials and so reads exactly like a fresh entry.
  * Running heads that repeat per page with a changing page number, in both the
    title-left/number-right and number-left/authors-right forms.
  * The "Click here to download ..." slip an editorial system staples after the bibliography.

The PDF is written directly (Courier, absolute text positioning) rather than converted from the
text with `cupsfilter`, which re-wraps lines past ~78 columns and would destroy the very column
alignment this fixture exists to test.
"""
from __future__ import annotations

import pathlib

ENTRY, CONT = 5, 7          # hanging indent: entry column, continuation column
HEAD_A = "Placeholder Architecture Recovery from Imaginary Forums"
HEAD_B = "Ahlgren et al."

lines: list[str] = []
_n = 0                      # margin line number; resets per page


def bare() -> None:
    """A margin number alone on its line (the number's baseline missed the text row)."""
    global _n
    _n += 1
    lines.append(f"{_n:>2}")


def txt(s: str, col: int) -> None:
    """A content line whose margin number was split onto the preceding line."""
    lines.append(" " * col + s)


def num(s: str, col: int) -> None:
    """A content line with its margin number inline in the gutter; content still at `col`."""
    global _n
    _n += 1
    lines.append(f"{_n}".ljust(col) + s)


def split_entry(s: str) -> None:
    bare()
    txt(s, ENTRY)


def split_cont(s: str) -> None:
    bare()
    txt(s, CONT)


def page_break() -> None:
    global _n
    lines.append("\f")
    _n = 0


# ── Page 1: front matter, then the bibliography opens in the split rendering ──
txt(HEAD_A, ENTRY)
lines.append("")
split_entry("Abstract This document exists only to exercise hallucite's reference")
split_cont("extraction. Every author, title, venue, and year below is invented.")
split_entry("1 Introduction")
split_entry("Placeholder body text, so the document carries a section before its")
split_cont("bibliography. It states nothing and cites nothing that exists.")
split_entry("References")
split_entry("Ahlgren PB, Boone QT (2019) Placeholder retrieval for imaginary code")
split_cont("search. Journal of Fictional Software 12(3):220-241")
split_entry("Baxter L, Crane MD, Dunne P (2021a) Invented tactics for nonexistent")
split_cont("build pipelines. Imaginary Transactions on Tooling 8(1):33-49")
# Mid-page, the margin numbers start rendering inline with the text.
num("Baxter L, Crane MD, Dunne P (2021b) Invented tactics for nonexistent", ENTRY)
num("build pipelines. Imaginary Transactions on Tooling 8(1):33-49", CONT)
# The wrapped-author-list trap: the (year) lands on the continuation line, and that
# continuation opens with a name that reads exactly like a fresh entry.
num("Corvino AA, Delgado R, Espinoza MT, Farrow K, Gutierrez L, Hollis N,", ENTRY)
num("Ivarsson P, Jorgensen M, et al. (2022) A placeholder survey of", CONT)
num("make-believe recommenders. arXiv preprint arXiv:220100000", CONT)
num("D'Amico AR, Enderby S (2018) Fictional metrics for unwritten modules.", ENTRY)
num("In: Proceedings of the 3rd Imaginary Symposium on Design, pp 14-25", CONT)

page_break()

# ── Page 2: running head form A (title left, page number right) ──────────────
lines.append(" " * ENTRY + HEAD_A + " " * 8 + "12")
lines.append("")
split_entry("de Vries MJ, Fontaine H (2020) Particle surnames and where to find")
split_cont("them. Journal of Invented Onomastics 4(2):77-95")
split_entry("Ibsen GD (1992) Determining an imaginary sample size. Tech. Rep. PL-6")
num("Jarrah T, Kowalski BR (2023) Nonexistent clustering for fabricated", ENTRY)
num("defect reports. Empirical Journal of Nothing 30(6):171", CONT)
num("Lindqvist A, Moreau CE, Nakamura T (2024) A make-believe study of", ENTRY)
num("untangling patterns. Imaginary Software Engineering 29(2):1-26", CONT)
num("Okonkwo IE (2017) An unsupervised approach to invented fragments. In:", ENTRY)
num("Proceedings of the 39th Fictional Conference on Software, pp 38-48", CONT)

page_break()

# ── Page 3: running head form B (page number left, authors right) ───────────
lines.append(" " * ENTRY + "14" + " " * 45 + HEAD_B)
lines.append("")
split_entry("Pemberton RS, Quist AA (2016) Collective intelligence for smarter")
split_cont("imaginary interfaces. In: Proc. 16th Fictional Conference, pp 51-60")
num("Rasmussen HL, Sorrentino VP (2015) Placeholder ontologies for design", ENTRY)
num("decisions. In: Proc. 2nd Invented Workshop on Variability, pp 54-61", CONT)
num("Thibault JR, Ueda K (2022) Asking about fictional debt: characteristics", ENTRY)
num("and identification. Journal of Imaginary Measurement 16:45-56", CONT)

page_break()

# ── Page 4: head form A again (so it repeats), then the attachment slip ─────
lines.append(" " * ENTRY + HEAD_A + " " * 8 + "16")
lines.append("")
split_entry("Vasquez ND, Whitfield C (2014) Ranking invented knowledge to assist")
split_cont("unreal development. In: Proc. 22nd Fictional Conference, pp 72-82")
num("Zambrano VL, Ashworth D (2025) Large fictional models for imaginary", ENTRY)
num("retrieval: a survey. Transactions on Nonexistent Systems 44(1):1-54", CONT)
lines.append("")
lines.append("Link(s) to supporting data")
lines.append("")
lines.append(" " * 29 + "Click here to download Link(s) to supporting data")
lines.append(" " * 29 + "https://example.invalid/placeholder-replication-package")


# ── Minimal PDF writer: Courier, one absolutely-positioned run per line ──────

def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(pages: list[list[str]], size: int = 9, leading: int = 12,
              left: int = 40, top: int = 750) -> bytes:
    objs: list[bytes] = []          # 1-indexed; objs[i] is object i+1

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    page_ids: list[int] = []
    kids_id = len(objs) + 2 * len(pages) + 1   # Pages object, allocated last

    for page in pages:
        run = [b"BT", f"/F1 {size} Tf".encode()]
        for i, line in enumerate(page):
            if line.strip():
                run.append(f"1 0 0 1 {left} {top - i * leading} Tm".encode())
                run.append(f"({_esc(line)}) Tj".encode())
        run.append(b"ET")
        stream = b"\n".join(run)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (kids_id, font, content)))

    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    pages_obj = add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids)))
    assert pages_obj == kids_id, f"page-tree id mismatch: {pages_obj} != {kids_id}"
    root = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += (b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, root, xref))
    return bytes(out)


if __name__ == "__main__":
    here = pathlib.Path(__file__).resolve().parent
    text = "\n".join(lines) + "\n"
    (here / "lineno_authoryear.txt").write_text(text)
    (here / "lineno_authoryear.pdf").write_bytes(
        build_pdf([p.split("\n") for p in text.split("\f")]))
    print(f"wrote lineno_authoryear.txt and .pdf ({len(lines)} lines, "
          f"{text.count(chr(12)) + 1} pages) to {here}")
