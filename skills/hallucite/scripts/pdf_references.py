"""Extract the bibliography from a paper's PDF file as a list of references.

These are paper PDF files in a mix of layouts: single- and two-column,
with or without the LaTeX `lineno` margin line numbers, and numeric, bracket-label,
or plain author-year bibliography styles. hallucinator's built-in MuPDF reader
mangles the `lineno` papers (line numbers bleed into titles/DOIs), so we do the
PDF-to-references step here and hand each segmented reference string to
hallucinator's `parse_reference`, which parses clean single-reference text well.

Pipeline:
  1. `pdftotext -layout` → split into pages.
  2. Column-aware linearization: detect a two-column gutter per page and read the
     left column fully, then the right (single-column pages pass through). This also
     stops the "References" header from sharing a line with the other column.
  3. Detect `lineno` and strip the leading margin number from every line.
  4. Find the References section.
  5. Auto-detect the entry style (numeric / bracket-label / author-year) and segment.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass

_SECTION_HEADERS = ("references", "bibliography", "references and notes",
                    "literature cited", "works cited")
_HEADER_NUM = re.compile(r"^(?:\d+|[ivxlc]+)[.)]?\s+", re.I)  # "7 ", "7. ", "VII. " before a header
_STOP_SECTION = re.compile(r"^(appendix|acknowledg)", re.I)
_LINENO_PREFIX = re.compile(r"^\s*\d{2,4}\s")
_MARGIN_LINENO = re.compile(r"^\s*\d{1,4}\s+")

# Entry-start patterns for the three bibliography styles.
_NUM = re.compile(r"^\[?(\d{1,3})\]?[.)]?\s+\S")          # "1 ", "1.", "[1] "
_YEAR = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
_BRACKET = re.compile(r"^\[[^\]]*(?:19|20)\d{2}[a-z]?[^\]]*\]")  # "[Smith et al.(2024)]"
_AUTHORYEAR = re.compile(r"^[^\W\d_][\w’'.\-]*,\s+[A-Z]")        # "Surname, I. ..."


@dataclass
class ExtractedRef:
    number: int            # printed number, or sequential index for non-numeric styles
    raw_text: str          # the reconstructed single-line citation text
    reference: object | None  # hallucinator.Reference, or None if it didn't parse


@dataclass
class ExtractionInfo:
    refs: list[ExtractedRef]
    lineno_on: bool
    section_found: bool
    style: str             # numeric | bracket | author-year | none


# ── PDF text → linearized lines ──────────────────────────────────────────────

def _pages(pdf_path: str) -> list[str]:
    try:
        out = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        raise RuntimeError("pdftotext not found; install poppler (e.g. `brew install poppler`).")
    return out.split("\x0c")


def _gutter(page_lines: list[str]) -> int | None:
    """Column position of a two-column gutter: a band of >=4 columns, in the
    middle 30-72% of the page width, that is whitespace on >97% of non-blank
    lines. Returns None for single-column pages."""
    nb = [l for l in page_lines if l.strip()]
    if len(nb) < 5:
        return None
    width = max(len(l) for l in nb)
    lo, hi = int(width * 0.30), int(width * 0.72)
    if hi <= lo:
        return None
    space_cols = [c for c in range(lo, hi)
                  if sum(c >= len(l) or l[c] == " " for l in nb) / len(nb) > 0.97]
    if not space_cols:
        return None
    band = [space_cols[0]]
    for c in space_cols[1:]:
        if c == band[-1] + 1:
            band.append(c)
        elif len(band) >= 4:
            break
        else:
            band = [c]
    return band[len(band) // 2] if len(band) >= 4 else None


def _linearize(pdf_path: str) -> list[str]:
    out: list[str] = []
    for page in _pages(pdf_path):
        plines = page.split("\n")
        g = _gutter(plines)
        if g is None:
            out.extend(plines)
        else:
            out.extend(l[:g].rstrip() for l in plines)
            out.extend(l[g:].rstrip() for l in plines)
    return out


def _strip_line_numbers(lines: list[str]) -> tuple[list[str], bool]:
    nb = [l for l in lines if l.strip()]
    if not nb:
        return lines, False
    if sum(bool(_LINENO_PREFIX.match(l)) for l in nb) / len(nb) <= 0.5:
        return lines, False
    return [_MARGIN_LINENO.sub("", l) for l in lines], True


def _references_section(lines: list[str]) -> list[str]:
    """Lines after the FIRST 'References'/'Bibliography'-style header. Tolerates a leading section
    number ('7 References', 'VII. References') and a trailing colon. Scanning forward (not
    backward) means a 'References' running page header repeated on later pages no longer chops the
    section down to its last page; those repeated header lines are dropped later as watermarks."""
    for i, line in enumerate(lines):
        head = _HEADER_NUM.sub("", line.strip().rstrip(" .:").lower())
        if head in _SECTION_HEADERS:
            return lines[i + 1:]
    return []


# ── Segmentation ─────────────────────────────────────────────────────────────

def _is_new_numeric(s: str, last: int) -> int | None:
    """The number if `s` starts a new numeric entry whose number continues the running sequence
    (advances by 1-3 from `last`); else None. The sequentiality guard stops stray years/page
    numbers from starting phantom refs. The sequence is anchored by `_numeric_anchor` (through the
    initial `last`), so a bibliography that legitimately starts above 1 is not dropped wholesale."""
    m = _NUM.match(s)
    if not m:
        return None
    num = int(m.group(1))
    return num if 0 < num - last <= 3 else None


def _numeric_anchor(section: list[str]) -> int:
    """The number the numeric sequence should start at: the smallest entry number N for which N+1
    and N+2 also appear as entry lines (a real ascending run). This skips a stray page/DOI number
    and lets a bibliography that legitimately starts above 1 be segmented rather than dropped,
    while still preferring the conventional start at 1. Falls back to the smallest number, else 1."""
    present = {int(_NUM.match(s).group(1)) for s in (ln.strip() for ln in section)
               if s and _NUM.match(s)}
    if not present:
        return 1
    runs = [n for n in present if n + 1 in present and n + 2 in present]
    return min(runs) if runs else min(present)


def _strip_numeric_label(s: str) -> str:
    return re.sub(r"^\[?\d{1,3}\]?[.)]?\s+", "", s, count=1)


def _dominant_style(section: list[str]) -> str:
    num = brk = ay = 0
    for line in section:
        s = line.strip()
        if not s:
            continue
        if _BRACKET.match(s):
            brk += 1
        elif _NUM.match(s):
            num += 1
        elif _AUTHORYEAR.match(s) and _YEAR.search(s[:300]):
            ay += 1
    if max(num, brk, ay) == 0:
        return "none"
    return max((("numeric", num), ("bracket", brk), ("author-year", ay)),
               key=lambda kv: kv[1])[0]


def _append(cur: str, s: str) -> str:
    if cur.endswith("-") and s[:1].islower():
        return cur + s              # soft line-break hyphen: join, keep hyphen
    return (cur + " " + s).strip()


def _segment(section: list[str], style: str) -> list[tuple[int, str]]:
    """Split the references section into (number, text) pairs for the detected
    style. Numeric entries keep their printed number; bracket and author-year
    entries get a sequential index. Continuation lines append to the current ref."""
    # Page footers and venue watermarks repeat verbatim across pages; a short line that
    # occurs 2+ times is running noise to drop (generic; no venue name hardcoded).
    repeated = {ln for ln, n in Counter(l.strip() for l in section if l.strip()).items()
                if n >= 2 and len(ln) <= 50}
    refs: list[tuple[int, str]] = []
    cur: str | None = None
    cur_num = 0
    last = (_numeric_anchor(section) - 1) if style == "numeric" else 0  # numeric sequentiality anchor
    seq = 0    # sequential counter (bracket / author-year)
    for line in section:
        s = line.strip()
        if not s or "???:" in s or s in repeated:  # blank / anonymized footer / repeated watermark
            continue
        # Stop at a trailing Appendix/Acknowledgments *heading* (short, standalone), but not at a
        # reference whose text merely begins with one of those words.
        if _STOP_SECTION.match(s) and len(s) <= 40 and not _NUM.match(s) and not _BRACKET.match(s):
            break

        new_text: str | None = None
        new_num = 0
        if style == "numeric":
            num = _is_new_numeric(s, last)
            if num is not None:
                last = new_num = num
                new_text = _strip_numeric_label(s)
        elif style == "bracket":
            if _BRACKET.match(s):
                seq = new_num = seq + 1
                new_text = _BRACKET.sub("", s, count=1).strip()
        elif style == "author-year":
            if _AUTHORYEAR.match(s) and _YEAR.search(s[:300]):
                seq = new_num = seq + 1
                new_text = s

        if new_text is not None:
            if cur is not None:
                refs.append((cur_num, cur))
            cur, cur_num = new_text, new_num
        elif cur is not None:
            cur = _append(cur, s)
    if cur is not None:
        refs.append((cur_num, cur))
    return refs


# ── Public API ───────────────────────────────────────────────────────────────

def _parse(extractor, text: str, prev_authors):
    """Parse one reference. hallucinator's heuristic parser occasionally rejects an
    otherwise-fine reference because of a long venue/footer tail, so on failure we
    retry on progressively shorter '. '-delimited prefixes (dropping the tail)."""
    r = extractor.parse_reference(text, prev_authors)
    if r is not None:
        return r
    parts = text.split(". ")
    for k in range(len(parts) - 1, 1, -1):
        r = extractor.parse_reference(". ".join(parts[:k]) + ".", prev_authors)
        if r is not None:
            return r
    return None


def extract_references(pdf_path: str, extractor) -> ExtractionInfo:
    """Extract and parse the bibliography of a PDF. `extractor` is a
    hallucinator.PdfExtractor used to parse each segmented reference string."""
    lines, lineno_on = _strip_line_numbers(_linearize(pdf_path))
    section = _references_section(lines)
    style = _dominant_style(section) if section else "none"
    segments = _segment(section, style) if style != "none" else []

    refs: list[ExtractedRef] = []
    prev_authors: list[str] | None = None
    for num, text in segments:
        parsed = _parse(extractor, text, prev_authors)
        if parsed is not None and parsed.authors:
            prev_authors = list(parsed.authors)
        refs.append(ExtractedRef(number=num, raw_text=text, reference=parsed))

    return ExtractionInfo(refs=refs, lineno_on=lineno_on,
                          section_found=bool(section), style=style)
