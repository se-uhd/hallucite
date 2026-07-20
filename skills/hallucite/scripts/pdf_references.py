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
  3. Detect `lineno` and blank out the margin number on every line -- overwriting it with spaces
     rather than deleting it, so the bibliography's hanging indent survives intact (see
     `_blank_margin`).
  4. Find the References section.
  5. Auto-detect the entry style (numeric / bracket-numeric / author-year-bracket / author-year)
     and segment. Bracket-numeric ("[12]") anchors on the bracketed label, not any leading
     `lineno` margin number, which otherwise hijacks the sequence and collapses the tail of the
     bibliography after a per-page line-number reset. Author-year anchors on the hanging indent
     when the section has one, because an author-year entry carries no label to anchor on and its
     year may sit on the following line.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field

_SECTION_HEADERS = ("references", "bibliography", "references and notes",
                    "literature cited", "works cited")
_HEADER_NUM = re.compile(r"^(?:\d+|[ivxlc]+)[.)]?\s+", re.I)  # "7 ", "7. ", "VII. " before a header
_STOP_SECTION = re.compile(r"^(appendix|acknowledg)", re.I)

# A `lineno` margin number, in the two shapes `pdftotext -layout` produces. Which one you get
# depends on whether the number's baseline lands on the text line's grid row, so a single paper
# switches between them mid-page -- both must count towards the detection ratio below, or a
# heavily line-numbered paper reads as un-numbered and every margin digit becomes data.
_MARGIN_BARE = re.compile(r"^\s*\d{1,4}\s*$")             # the number alone on its own line
_MARGIN_GUTTER = re.compile(r"^\s*\d{1,4}\s{2,}(?=\S)")   # the number in the gutter before content

# Entry-start patterns for the bibliography styles.
_NUM = re.compile(r"^\[?(\d{1,3})\]?[.)]?\s+\S")          # "1 ", "1.", "[1] "
_YEAR = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
_BRACKET = re.compile(r"^\[[^\]]*(?:19|20)\d{2}[a-z]?[^\]]*\]")  # "[Smith et al.(2024)]"

# An author-list opening, in the two conventions that dominate: APA-ish "Surname, I." and the
# Springer/Elsevier "Surname AB, Surname CD" (initials after the surname, no comma between the
# two). Matching only the former silently reclassifies every Springer bibliography as some other
# style. A leading lowercase particle ("de Dieu MJ", "van Rijn A") and an apostrophe or hyphen
# inside the surname ("D’Souza AR", "Yorke-Smith N") are both common enough to allow for.
# Initials are capitals; matching them case-insensitively lets any short lowercase word stand in
# for them, and a running head ("... Questions on Stack Overflow") then parses as an author list.
_UP = r"[A-ZÀ-ÖØ-Þ]"
_PARTICLE = r"(?:(?:d[aeiou]|van|von|del|della|der|den|dos|la|le|ten|ter)\s+)?"
_AUTHORYEAR = re.compile(
    rf"^{_PARTICLE}{_UP}[\w’'.\-]*"                       # surname
    rf"(?:\s+{_UP}[\w’'.\-]*)*?"                          # further surname words
    rf"(?:,\s+{_UP}|\s+{_UP}{{1,4}}[,(\s])",              # ", I." (APA) or " AB," (Springer)
    re.UNICODE)

# A bracket-numeric entry label "[12]", optionally preceded by a `lineno` margin number that
# pdftotext -layout leaves in a wide left column ("12   [13]  Author ..."). The two numbers are a
# trap: when the margin number bleeds in, plain numeric segmentation locks onto it instead of the
# real "[13]" label, and a per-page line-number reset then collapses the rest of the bibliography
# into one segment. Anchoring on the bracketed label avoids both.
_BRACKET_NUM = re.compile(r"^(?:\d{1,4}\s{2,})?\[(\d{1,3})\][.)]?\s+\S")
_MARGIN_NUM_ONLY = re.compile(r"^\d{1,4}$")        # a `lineno` number alone on a line (drop)
_LEAD_MARGIN_NUM = re.compile(r"^\d{1,4}\s{2,}")   # a `lineno` number in the gutter before content
# The gap `-layout` leaves between a running title and its page number. Justified reference text
# never contains one, so it distinguishes page furniture from a real entry.
_WIDE_GAP = re.compile(r"\S\s{8,}\S")


@dataclass
class ExtractedRef:
    number: int            # printed number, or sequential index for non-numeric styles
    raw_text: str          # the reconstructed single-line citation text
    reference: object | None  # hallucinator.Reference, or None if it didn't parse
    # `raw_text` with the hyphens closed by line-break joins removed ("Experimen-tation" ->
    # "Experimentation"), or None when no such join happened. The kept-hyphen form is right for a
    # real compound broken at its own hyphen and wrong for a soft-hyphenated word -- and FTS
    # backends miss the wrong form entirely -- so verification tries this variant when the
    # original fails.
    alt_text: str | None = None


@dataclass
class ExtractionInfo:
    refs: list[ExtractedRef]
    lineno_on: bool
    section_found: bool
    style: str             # numeric | bracket | author-year | none
    # Author-year references whose text carries two or more "(year)" author-block signatures:
    # the shape a silently merged pair of entries leaves behind when no hanging indent delimits
    # them and the second entry's year sat on a wrapped line. A warning, not a verdict -- but a
    # merged entry never reaches verification on its own, so it must not stay invisible.
    suspect_merged: list[int] = field(default_factory=list)


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


def _blank_margin(line: str, margin_col: int) -> str:
    """Replace a `lineno` margin number with the spaces it occupied, keeping every remaining
    character in its original column. Deleting the digits instead would shift a numbered line left
    relative to an unnumbered one, destroying the bibliography's hanging indent -- the only signal
    that separates an author-year entry from its continuation lines.

    A number ALONE on its line is blanked only at the margin column (within the 1-2 columns that
    right-aligned digit widths shift it). A lone number at a continuation indent is *content* -- a
    page number that wrapped onto its own line ("...19(3):619–" / "654") -- and blanking it
    silently truncates the citation it belongs to. The gutter shape (number, gap, then text on
    the same line) stays ungated: there the number is furniture whatever its column -- a `lineno`
    margin or the page number of a running head -- and the text keeps its own position."""
    if _MARGIN_BARE.match(line):
        indent = len(line) - len(line.lstrip())
        return line if indent > margin_col + 2 else ""
    m = _MARGIN_GUTTER.match(line)
    return " " * m.end() + line[m.end():] if m else line


def _strip_line_numbers(lines: list[str]) -> tuple[list[str], bool]:
    nb = [l for l in lines if l.strip()]
    if not nb:
        return lines, False
    matches = [l for l in nb if _MARGIN_BARE.match(l) or _MARGIN_GUTTER.match(l)]
    if len(matches) / len(nb) <= 0.5:
        return lines, False
    # The margin column is where the mass of the matches sits. Gate the blanking on it, so the
    # rare wrapped page number ("654" alone at a continuation indent) survives as content while
    # every true margin number -- vastly more frequent, all at the left margin -- is blanked.
    margin_col = Counter(len(l) - len(l.lstrip()) for l in matches).most_common(1)[0][0]
    return [_blank_margin(l, margin_col) for l in lines], True


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


def _bracket_numeric_anchor(section: list[str]) -> int:
    """`_numeric_anchor` for bracket-numeric labels: the smallest "[N]" that starts a real
    ascending run, so a stray "[1]" inside a reference does not anchor the sequence below the
    first real entry."""
    present = {int(_BRACKET_NUM.match(s).group(1)) for s in (ln.strip() for ln in section)
               if s and _BRACKET_NUM.match(s)}
    if not present:
        return 1
    runs = [n for n in present if n + 1 in present and n + 2 in present]
    return min(runs) if runs else min(present)


def _is_new_bracket_numeric(s: str, last: int) -> int | None:
    """The label number if `s` starts a new "[N]" entry continuing the running sequence (advances
    1-3 from `last`); else None. Keyed on the bracketed label, not any leading `lineno` margin
    number, so margin numbers cannot masquerade as entries and a per-page margin reset cannot
    collapse the tail of the bibliography into one segment."""
    m = _BRACKET_NUM.match(s)
    if not m:
        return None
    num = int(m.group(1))
    return num if 0 < num - last <= 3 else None


def _common_cols(section: list[str]) -> list[int]:
    """The indents the section's text block actually uses, in order. A column has to carry real
    weight to count: thresholding on a bare line count instead lets three stray page numbers in the
    right margin pass for a column of body text, which stretches the block far enough to swallow
    the furniture the block is meant to exclude."""
    cols = Counter(len(l) - len(l.lstrip()) for l in section if l.strip())
    total = sum(cols.values())
    return sorted(c for c, n in cols.items() if n >= max(3, total * 0.05))


def _body_col(section: list[str]) -> int:
    """The deepest column the bibliography's own text block uses. Anything well past it is page
    furniture or a submission-system attachment slip, not a reference."""
    return max(_common_cols(section), default=0)


def _entry_indent(section: list[str]) -> int | None:
    """The column an author-year entry starts at, when the section is laid out with a hanging
    indent (entries flush at one column, their continuations at a deeper one); else None.

    Author-year entries carry no "[12]"-style label to anchor segmentation on, and the `(year)` is
    not reliably on the entry's first line -- an author list long enough to wrap pushes it onto the
    next one. Indentation is what actually delimits the entries, and it is unambiguous once
    `_blank_margin` has preserved the columns. Without it, every continuation line that happens to
    open with a name ("Joseph N, Brockman G, et al. (2021b) ...") starts a phantom reference."""
    counts = Counter(len(l) - len(l.lstrip()) for l in section if l.strip())
    total = sum(counts.values())
    if not total:
        return None
    # Require at least two weighted levels, so a stray indented line cannot invent a hanging
    # indent, and require them to cover the section, so a ragged layout falls back to the regex.
    common = _common_cols(section)
    if len(common) < 2:
        return None
    if sum(counts[c] for c in common) / total < 0.8 or counts[common[0]] < 3:
        return None
    return common[0]


def _head_norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "", s)).strip()


def _running_heads(section: list[str], doc: list[str] | None = None) -> set[str]:
    """Lines to drop as page furniture: running heads and footers. They repeat on every page but
    differ in their page number, so they must be compared with digits removed. That comparison
    alone is too blunt -- short continuation lines like "pp 164-171" collapse onto each other too
    -- so a repeated line also has to sit outside the text block, in one of the two ways a running
    head does: it keeps the wide gap `-layout` renders between a running title and its page
    number, or (once `_blank_margin` has taken that page number away) it is indented far past any
    column the bibliography itself uses. Justified reference text is neither.

    Repetition is counted over the whole document (`doc`), not the section: a head repeats on
    every page of the paper, but a bibliography spanning n pages contains only n-1 of those
    lines, so a two-page bibliography sees its head exactly once and a section-only count can
    never reach 2 -- which is how a running head ended up glued into a reference's title."""
    body = _body_col(section)
    counts: Counter[str] = Counter(n for n in (_head_norm(l) for l in (doc or section))
                                   if n)
    furniture: set[str] = set()
    for line in section:
        s = line.strip()
        if not s:
            continue
        # Judge the shape on the raw line -- normalizing collapses the very gap we look for.
        if _WIDE_GAP.search(s) or (len(line) - len(line.lstrip())) > body + 10:
            furniture.add(_head_norm(s))
    return {n for n in furniture if n and counts[n] >= 2}


def _strip_bracket_label(s: str) -> str:
    return re.sub(r"^(?:\d{1,4}\s{2,})?\[\d{1,3}\][.)]?\s+", "", s, count=1)


def _strip_numeric_label(s: str) -> str:
    return re.sub(r"^\[?\d{1,3}\]?[.)]?\s+", "", s, count=1)


def _dominant_style(section: list[str]) -> str:
    num = brk = bnum = ay = 0
    for line in section:
        s = line.strip()
        if not s:
            continue
        if _BRACKET.match(s):           # "[Smith 2024]" author-year bracket
            brk += 1
        elif _BRACKET_NUM.match(s):     # "[12]" numeric bracket (maybe lineno-prefixed)
            bnum += 1
        elif _NUM.match(s):             # "12." / "12  ..." (also lineno-prefixed continuations)
            num += 1
        elif _AUTHORYEAR.match(s) and _YEAR.search(s[:300]):
            ay += 1
    # A plain-numeric bibliography never carries bracketed numeric labels, so a handful of "[N]"
    # entry markers settle the style even when lineno-prefixed continuation lines push the bare
    # "numeric" tally higher.
    if bnum >= 3 and bnum >= brk and bnum >= ay:
        return "bracket-numeric"
    if max(num, brk, ay) == 0:
        return "none"
    return max((("numeric", num), ("bracket", brk), ("author-year", ay)),
               key=lambda kv: kv[1])[0]


def _append(cur: str, s: str) -> tuple[str, int | None]:
    """Join a continuation line onto the current reference. Returns the joined text and, when the
    join closed a line-break hyphen, that hyphen's index in the joined text. The hyphen is kept --
    it is correct for a real compound broken at its own hyphen -- but its position is recorded so
    the caller can also offer the dehyphenated variant, which is correct for a soft-hyphenated
    word ("Experimen-tation"). Neither form is right for both, and FTS lookups miss the wrong one."""
    if cur.endswith("-") and s[:1].islower():
        return cur + s, len(cur) - 1  # soft line-break hyphen: join, keep hyphen, remember it
    return (cur + " " + s).strip(), None


def _dehyphenate(text: str, joins: list[int]) -> str | None:
    """`text` with the soft-join hyphens at `joins` removed, or None when there were none."""
    if not joins:
        return None
    out, prev = [], 0
    for i in joins:
        out.append(text[prev:i])
        prev = i + 1
    out.append(text[prev:])
    return "".join(out)


def _segment(section: list[str], style: str,
             doc: list[str] | None = None) -> list[tuple[int, str, str | None]]:
    """Split the references section into (number, text, dehyphenated-alt) triples for the
    detected style. Numeric entries keep their printed number; bracket and author-year entries
    get a sequential index. Continuation lines append to the current ref. The alt is the text
    with line-break-join hyphens removed (None when no join happened); `doc` is the whole
    document's lines, used to count running-head repetitions beyond the section."""
    # Page footers and venue watermarks repeat verbatim across pages; a short line that
    # occurs 2+ times is running noise to drop (generic; no venue name hardcoded).
    repeated = {ln for ln, n in Counter(l.strip() for l in section if l.strip()).items()
                if n >= 2 and len(ln) <= 50}
    heads = _running_heads(section, doc)
    refs: list[tuple[int, str, str | None]] = []
    cur: str | None = None
    cur_joins: list[int] = []
    cur_num = 0
    if style == "numeric":
        last = _numeric_anchor(section) - 1          # numeric sequentiality anchor
    elif style == "bracket-numeric":
        last = _bracket_numeric_anchor(section) - 1  # bracket-label sequentiality anchor
    else:
        last = 0
    # Only author-year needs the hanging indent; the labelled styles anchor on their own labels.
    entry_col = _entry_indent(section) if style == "author-year" else None
    body_col = _body_col(section)
    seq = 0    # sequential counter (bracket / author-year)
    for line in section:
        s = line.strip()
        if not s or "???:" in s or s in repeated:  # blank / anonymized footer / repeated watermark
            continue
        if _head_norm(s) in heads:  # running head / footer
            continue
        indent = len(line) - len(line.lstrip())
        # Once the hanging indent is known, the entry column is the left edge of the bibliography
        # and `body_col` its right-most; text outside that block belongs to something else -- a
        # stray page number, or the "Click here to download ..." slip an editorial system staples
        # after the last reference, which otherwise lands inside it.
        if entry_col is not None and not entry_col <= indent <= body_col + 10:
            continue
        # A `lineno` margin number alone on a line is noise between entries; drop it so it neither
        # starts a phantom entry nor pollutes the previous reference's text.
        if style == "bracket-numeric" and _MARGIN_NUM_ONLY.match(s):
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
        elif style == "bracket-numeric":
            num = _is_new_bracket_numeric(s, last)
            if num is not None:
                last = new_num = num
                new_text = _strip_bracket_label(s)
        elif style == "bracket":
            if _BRACKET.match(s):
                seq = new_num = seq + 1
                new_text = _BRACKET.sub("", s, count=1).strip()
        elif style == "author-year":
            # With a hanging indent the column is authoritative: it alone separates an entry from a
            # continuation that opens with a name, and it admits an entry whose `(year)` wrapped
            # onto the next line. Without one, fall back to requiring the year on the entry line.
            starts = (indent <= entry_col if entry_col is not None
                      else bool(_YEAR.search(s[:300])))
            if starts and _AUTHORYEAR.match(s):
                seq = new_num = seq + 1
                new_text = s

        if new_text is not None:
            if cur is not None:
                refs.append((cur_num, cur, _dehyphenate(cur, cur_joins)))
            cur, cur_num, cur_joins = new_text, new_num, []
        elif cur is not None:
            # Strip the gutter `lineno` number off a continuation line before joining it, so margin
            # digits do not land inside titles, venues, or page ranges.
            if style == "bracket-numeric":
                s = _LEAD_MARGIN_NUM.sub("", s, count=1)
            cur, join = _append(cur, s)
            if join is not None:
                cur_joins.append(join)
    if cur is not None:
        refs.append((cur_num, cur, _dehyphenate(cur, cur_joins)))
    return refs


def _suspect_merges(refs: list[ExtractedRef], style: str) -> list[int]:
    """Author-year references whose text carries two or more "(year)" labels. An entry carries
    exactly one; two is the shape a silent merge leaves behind -- with no hanging indent to
    delimit entries, an entry whose year wrapped onto its next line is glued into its predecessor
    and never verified on its own. A flag for the audit to warn about, never a verdict."""
    if style != "author-year":
        return []
    return [r.number for r in refs if len(_YEAR.findall(r.raw_text)) >= 2]


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
    segments = _segment(section, style, lines) if style != "none" else []

    refs: list[ExtractedRef] = []
    prev_authors: list[str] | None = None
    for num, text, alt in segments:
        parsed = _parse(extractor, text, prev_authors)
        if parsed is not None and parsed.authors:
            prev_authors = list(parsed.authors)
        refs.append(ExtractedRef(number=num, raw_text=text, reference=parsed, alt_text=alt))

    return ExtractionInfo(refs=refs, lineno_on=lineno_on,
                          section_found=bool(section), style=style,
                          suspect_merged=_suspect_merges(refs, style))
