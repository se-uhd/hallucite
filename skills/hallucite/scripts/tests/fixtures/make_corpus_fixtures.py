#!/usr/bin/env python3
"""Derive a synthetic extraction fixture from each corpus paper.

Takes each real PDF's `pdftotext -layout` output, replaces every content word -- author names and
title words -- with an invented word of the SAME LENGTH, and writes the result back out as a PDF
whose text layout is byte-identical to the substituted text. Column positions, indents, line
breaks, running heads, margin numbers and page furniture all survive, because nothing changes
length; what does not survive is anyone's authorship or title.

The fixture is only worth committing if it still behaves like the paper it came from, so the
generator refuses to write one unless `extract_references` reports the same style, the same
reference count, the same unparsed count and the same missing-number set for the synthetic paper
as for the real one.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
sys.path.insert(0, str(SCRIPTS))
import pdf_references as P          # noqa: E402
import reference_parser as RP       # noqa: E402

# ── what must survive substitution ───────────────────────────────────────────
#
# The parser reads structure, not meaning: the word that ends an author list, the word that opens a
# venue, the marks around an identifier. Cipher those and the fixture stops reproducing the paper.
# Everything else -- surnames, given names, title words -- is content and is replaced.
KEEP = {
    # connectors and the author-list vocabulary
    "and", "et", "al", "with", "eds", "ed", "editors", "editor", "jr", "sr",
    # section headings: the extractor finds the bibliography by its own name
    "references", "reference", "bibliography", "acknowledgements", "acknowledgments", "appendix",
    # the words that mark a venue, an edition, or a locator
    "in", "proc", "proceedings", "conf", "conference", "symposium", "workshop", "congress",
    "journal", "transactions", "trans", "magazine", "letters", "bulletin", "review", "reviews",
    "international", "national", "annual", "acm", "ieee", "usenix", "springer", "elsevier",
    "wiley", "press", "university", "univ", "college", "school", "institute", "society",
    "technical", "report", "tech", "rep", "thesis", "dissertation", "chapter", "book",
    "edition", "revised", "preprint", "arxiv", "corr", "abs", "doi", "url", "http", "https",
    "www", "org", "com", "net", "edu", "gov", "io", "pdf", "html", "vol", "volume", "no", "num",
    "pp", "p", "pages", "page", "article", "isbn", "issn",
    "accessed", "available", "online", "retrieved", "last", "visited", "cited",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
    # generic enough to be venue text as often as title text; cutting them breaks venues
    "software", "engineering", "computer", "computing", "science", "sciences", "systems",
    "system", "technology", "information", "data", "the", "of", "for", "on", "a", "an", "to",
    "by", "from", "at", "its", "via",
}

# Name particles. A surname's particle is what tells `_ENTRY_HEAD` the line opens an entry, so
# ciphering "de Castro-Cabrera" to "pe Tarnta-Kiprixp" ends the hanging-indent block on the spot
# and the bibliography stops there. Held to the parser's own list so the two cannot drift.
_PARTICLES = {"da", "de", "di", "do", "du", "van", "von", "del", "della", "der", "den", "dos",
              "la", "le", "ten", "ter"}
assert all(re.fullmatch(P._PARTICLE, w + " ") for w in _PARTICLES), \
    "particle list has drifted from pdf_references._PARTICLE"
KEEP |= _PARTICLES

# The bibliography's own heading, and the fragment a small-caps heading breaks into. IEEE sets it
# with a full-size initial and `pdftotext` emits the size change as a space, so "REFERENCES" leaves
# an "EFERENCES" that no heading list contains -- and on a two-column page the heading shares its
# text line with the right-hand column, so protecting whole heading *lines* does not reach it.
# Eight of the corpus's fifty-five papers lost their whole bibliography to exactly that.
KEEP |= {w for h in P._SECTION_HEADERS for word in h.split() for w in (word, word[1:]) if w}

_WORD = re.compile(r"[A-Za-z]+")
# Invented syllables; a word is rebuilt from these to its exact original length.
_SYL = ("bar", "quo", "vex", "lum", "dor", "kip", "nas", "tef", "wob", "zil", "mur", "gan",
        "pel", "rix", "solv", "tarn", "ulme", "vond", "wisk", "yarn", "zeph", "cran", "drel")


def _invent(word: str) -> str:
    """A deterministic invented word of exactly `word`'s length, keeping its capitalisation shape.

    Deterministic on the lowercased word, so one author is one invented name everywhere in the
    corpus and a repeated title word stays repeated -- the structure a bibliography carries."""
    n = len(word)
    seed = int(hashlib.sha256(word.lower().encode()).hexdigest()[:12], 16)
    out = []
    while len(out) < n:
        out.extend(_SYL[seed % len(_SYL)])
        seed //= len(_SYL)
        if seed == 0:
            seed = int(hashlib.sha256("".join(out).encode()).hexdigest()[:12], 16)
    built = "".join(out)[:n]
    # Keep the case pattern so initials stay initials and Title Case stays Title Case.
    return "".join(c.upper() if word[i].isupper() else c for i, c in enumerate(built))


def _is_section_heading(line: str) -> bool:
    """Does `_references_section` read this line as the bibliography's heading?

    Asked exactly the way the extractor asks it, including the space-stripped spelling. IEEE sets
    the heading in small caps with a full-size initial and `pdftotext` emits the size change as a
    space, so "REFERENCES" arrives as "R EFERENCES" -- and ciphering the "EFERENCES" half loses the
    section for the whole paper. Ten of the corpus's fifty-five did exactly that."""
    head = line.strip().rstrip(".").lower()
    head = re.sub(r"^\d+[.)]?\s*", "", head)
    return (head in P._SECTION_HEADERS
            or head.replace(" ", "") in P._SECTION_HEADERS_NOSPACE)


def _substitute(text: str) -> str:
    def repl(m):
        w = m.group(0)
        return w if (w.lower() in KEEP or len(w) == 1) else _invent(w)
    return "\n".join(line if _is_section_heading(line) else _WORD.sub(repl, line)
                      for line in text.split("\n"))


# ── PDF writing (Courier, absolute positioning; never re-wraps) ──────────────

def _cp1252(s: str) -> bytes:
    """Encode for WinAnsi, one byte per character, so no substitution changes a line's length.

    A character cp1252 cannot hold is folded to its base letter, and failing that to `x` for a
    letter and `-` for anything else. Dropping to `?`, as a plain `replace` does, would turn a
    letter into punctuation, and the parser reads punctuation as field boundaries."""
    out = bytearray()
    for ch in s:
        try:
            out += ch.encode("cp1252")
            continue
        except UnicodeEncodeError:
            pass
        base = unicodedata.normalize("NFD", ch)[:1]
        try:
            out += base.encode("cp1252")
        except UnicodeEncodeError:
            out += b"x" if ch.isalpha() else b"-"
    return bytes(out)


def _esc(b: bytes) -> bytes:
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(pages: list[list[str]], size: float = 9.0, leading: float = 12.0,
              left: float = 36.0, top_pad: float = 36.0) -> bytes:
    """One absolutely-positioned Courier run per line, on a page sized to fit the widest line.

    The MediaBox is computed rather than fixed: a two-column bibliography comes out of
    `pdftotext -layout` up to 200 columns wide, and on a Letter page those columns would run off
    the sheet, where `-layout` can no longer tell one column from the other."""
    char_w = size * 0.6                       # Courier advance width
    widest = max((len(l) for pg in pages for l in pg), default=80)
    tallest = max((len(pg) for pg in pages), default=1)
    width = left * 2 + widest * char_w
    height = top_pad * 2 + tallest * leading
    top = height - top_pad

    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
                b"/Encoding /WinAnsiEncoding >>")
    page_ids: list[int] = []
    kids_id = len(objs) + 2 * len(pages) + 1

    for page in pages:
        run = [b"BT", f"/F1 {size} Tf".encode()]
        for i, line in enumerate(page):
            y = top - i * leading
            # One positioned run per word, not one per line. A single run spanning a two-column
            # page makes the gutter a long stretch of rendered spaces, and `pdftotext -layout`
            # rebuilds that width by rounding -- so the right column's left edge jitters by a
            # character from line to line and the blank band `_gutter` looks for is not blank.
            # Positioning each word puts every column back where it was, exactly.
            for m in re.finditer(r"\S+", line):
                x = left + m.start() * char_w
                run.append(f"1 0 0 1 {x:.2f} {y:.2f} Tm".encode())
                run.append(b"(" + _esc(_cp1252(m.group(0))) + b") Tj")
        run.append(b"ET")
        stream = b"\n".join(run)
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(add(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
            % (kids_id, width, height, font, content)))

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


# ── the fixture ──────────────────────────────────────────────────────────────

def shape(pdf_path: Path) -> tuple:
    """What extraction makes of a paper: the tuple a fixture has to reproduce."""
    info = P.extract_references(str(pdf_path), RP)
    return (info.style, len(info.refs),
            sum(1 for r in info.refs if r.reference is None),
            tuple(sorted(info.missing_numbers or ())))


_HEAD = re.compile(r"^\s*(?:\d+\.?\s*)?(R\s?E\s?F\s?E\s?R\s?E\s?N\s?C\s?E\s?S?"
                   r"|B\s?I\s?B\s?L\s?I\s?O\s?G\s?R\s?A\s?P\s?H\s?Y|References|Bibliography)\b",
                   re.I)


def first_ref_page(pages: list[str]) -> int:
    for i in range(len(pages) - 1, -1, -1):
        if any(_HEAD.match(l) for l in pages[i].split("\n")):
            return i
    return max(0, len(pages) - 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("corpus", nargs="?", default=str(Path.home() / "hallucite" / "corpus"),
                    help="directory of the real papers (default: ~/hallucite/corpus)")
    ap.add_argument("out", nargs="?", default=str(HERE / "corpus"),
                    help="where to write the fixtures (default: the corpus/ beside this script)")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    corpus, out = Path(a.corpus), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ok = bad = 0
    expected: list[str] = []
    for pdf in sorted(corpus.glob("*.pdf")):
        if a.only and a.only not in pdf.name:
            continue
        want = shape(pdf)
        raw = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                             capture_output=True, text=True, check=True).stdout
        pages = raw.split("\f")
        start = first_ref_page(pages)
        made = None
        for back in (0, 1, 2, 4, 8, 99):          # widen until the shape reproduces
            s = max(0, start - back)
            text = _substitute("\f".join(pages[s:]))
            pdf_bytes = build_pdf([pg.split("\n") for pg in text.split("\f")])
            tmp = out / (pdf.stem + ".pdf")
            tmp.write_bytes(pdf_bytes)
            try:
                got = shape(tmp)
            except Exception as e:                # noqa: BLE001
                got = ("error", str(e), 0, ())
            if got == want:
                (out / (pdf.stem + ".txt")).write_text(text, encoding="utf-8")
                made = (s, len(pages) - s)
                break
        if made:
            ok += 1
            expected.append("\t".join([pdf.stem, want[0], str(want[1]), str(want[2]),
                                       ",".join(str(n) for n in want[3])]))
            print(f"  ok   {pdf.stem:28s} {want[0]:16s} refs={want[1]:4d} "
                  f"pages={made[1]} (from {made[0]})")
        else:
            bad += 1
            (out / (pdf.stem + ".pdf")).unlink(missing_ok=True)
            print(f"  FAIL {pdf.stem:28s} want={want} got={got}")
    if not a.only:
        (out / "EXPECTED.tsv").write_text(
            "# paper\tstyle\treferences\tunparsed\tmissing_numbers\n"
            "# Written from the REAL papers, not from the fixtures, so the committed net is\n"
            "# anchored to what the corpus actually extracts. Regenerate with this script.\n"
            + "\n".join(expected) + "\n", encoding="utf-8")
    print(f"\n{ok} reproduced, {bad} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
