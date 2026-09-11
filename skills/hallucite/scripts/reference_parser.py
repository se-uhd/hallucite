"""One segmented bibliography entry to `{title, authors, doi, arxiv_id}`.

hallucite reads and segments the bibliography itself (`pdf_references.py`); this module takes one
finished entry and reads its fields. `VERIFICATION-SPEC.md` states what it has to get right, and
`characterize.py` holds it to real references.

The corpus styles it has to cover, and how each is recognised:

* ACM / Chicago -- `Authors. 2023. Title. In Venue. pages. doi:...`, split on the standalone year.
* APA -- `Authors (2023). Title. Journal, 12(3), 1-10.`, split on the parenthesised year.
* IEEE -- `A. Author and B. Other, "Title," in Proc. Conf., 2020, pp. 1-10.`, split on the quotes.
* Springer / LNCS -- `Wohlin, C., Runeson, P.: Title. Venue (2012)`, split on the colon that follows
  an inverted-name list.
* Everything else -- the first sentence after a prefix that reads as an author list.

Two rules carry most of the correctness. The title is one *sentence*, so it ends at a period that
is not an abbreviation or an initial -- which keeps a venue that follows without an `In` out of the
title. And a question mark ends the title only when what follows reads as a venue, because
"Can LLMs Really Reason about Code? Studying How Well ..." is one title and
"Known vulnerabilities ... Where are the fixes? IEEE Security & Privacy 22, 2 (2024)" is two fields.

Nothing is invented. A field the entry does not carry is absent from the result, and a citation
whose title cannot be located at all returns None so the audit can record it as `unparsed`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# The result shape the audit, the triage step and the verifier all read.
@dataclass
class Reference:
    title: str
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    arxiv_id: str | None = None
    urls: list[str] = field(default_factory=list)
    raw_citation: str = ""
    original_number: int | None = None


# ── text normalisation ───────────────────────────────────────────────────────

# Quotation marks, paired: a curly opener closes only on its own partner, or a title carrying a
# quoted phrase ends at the phrase's opening mark.
_QUOTE_PAIRS = {'"': '"', "“": "”", "„": "“”", "«": "»", "‟": "”", "‘": "’", "`": "'"}
_OPEN_Q = "".join(_QUOTE_PAIRS)
_CLOSE_Q = "".join(set("".join(_QUOTE_PAIRS.values())))

# A hyphen followed by a space between two letters is a line break the layout put there
# ("Test Co- Evolution"), never a word's own punctuation. Closing the space leaves an ordinary
# hyphenated form, which both the DBLP and the CrossRef matcher already try in either reading.
# Except before a conjunction: "Joining Player- and Data-Driven Analytics" is a *suspended*
# hyphen standing in for the second half of a compound, and closing it invents the word
# "Player-and".
_HYPHEN_GAP = re.compile(r"(?<=[A-Za-z])-\s+(?!(?:and|or|und|oder)\s)(?=[A-Za-z])")


def _clean(text: str) -> str:
    return _HYPHEN_GAP.sub("-", " ".join((text or "").split()))


# ── identifiers ──────────────────────────────────────────────────────────────

# A DOI is a `10.<registrant>/<suffix>`. The optional space after the slash is a line break the
# bibliography took inside the identifier ("doi:10.1145/ 3663529.3663801"); without it that entry
# carries no DOI at all, which costs the DOI backend its cheapest confirmations.
_DOI = re.compile(r"10\.\d{4,9}\s?/\s?[^\s\"]+", re.I)
# Trailing punctuation belongs to the sentence, not to the identifier. A closing bracket is only
# trimmed when nothing opened it inside the DOI.
_DOI_TRAIL = ".,;:'’”\"‘“"

# Four digits of yymm, then four or five of sequence. The lookahead matters: without it a
# malformed six-digit id is silently truncated to a real-looking five, and hallucite would then
# report a working arXiv record for an identifier the paper does not cite.
_ARXIV_NEW = r"\d{4}\.\d{4,5}(?!\d)"
_ARXIV_OLD = r"[a-z][a-z-]+(?:\.[A-Z]{2})?/\d{7}(?!\d)"
_ARXIV = re.compile(
    r"(?:arxiv(?:\.org)?[:/\s]*(?:preprint\s+)?(?:arxiv[:\s]*)?(?:abs/|pdf/)?|10\.48550/arxiv\.|"
    # A bare "abs/" is how a CoRR citation writes it ("CoRR, abs/2411.19043, 2024").
    r"\babs/)"
    rf"({_ARXIV_NEW}|{_ARXIV_OLD})(?:v\d+)?", re.I)
_URL = re.compile(r"https?://[^\s<>\"]+", re.I)


def _trim_identifier(s: str) -> str:
    while s and s[-1] in _DOI_TRAIL:
        s = s[:-1]
    while s.endswith(")") and s.count(")") > s.count("("):
        s = s[:-1]
    while s.endswith("]") and s.count("]") > s.count("["):
        s = s[:-1]
    # Wiley's older DOIs carry angle brackets of their own
    # ("10.1002/(SICI)1097-0266(199902)20:2<175::AID-SMJ13>3.0.CO;2-J"), so one is only stripped
    # when nothing in the identifier opened it -- a `<https://doi.org/...>` delimiter.
    while s.endswith(">") and s.count(">") > s.count("<"):
        s = s[:-1]
    return s


# The rest of an identifier, on the far side of a line break. Digit-led, because that is what a
# broken DOI resumes with and an ordinary following word does not -- or hyphen-led into a digit,
# which is how an Elsevier book DOI resumes ("10.1016/B978 -0-12-396535-6.00001-6").
_DOI_CONTINUES = re.compile(r"\s+((?:\d|-\d)[0-9A-Za-z._()/-]*)")
# What follows an identifier's own period when the layout broke it there: runs of digits, with
# periods between them ("8281704", "2020.9231762", "03.006"). Over the corpus every one of the 60
# period breaks resumes this way, and nothing else does -- a four-digit year alone is the entry's
# own date running on, and a word is the next field.
_DOI_DIGITS = re.compile(r"^\d+(?:\.\d+)*$")
_YEAR_ALONE = re.compile(r"^(?:19|20)\d{2}$")


def _continues(raw: str, part: str) -> bool:
    """Does `part`, the token after the untrimmed identifier `raw`, continue it across a line
    break that fell on one of the identifier's own separators?

    A hyphen-led run of digits always does: no bibliography prints " -0-12-" after a DOI for any
    other reason. Digits after a period do when the period was the identifier's, not the
    sentence's -- "doi:10.1109/ICET.2017. 8281704" is one DOI, "doi:10.1145/3498537. 2020." is a
    DOI and the entry's year."""
    if part.startswith("-"):
        return True
    if not raw.endswith("."):
        return False
    part = _trim_identifier(part)
    return bool(_DOI_DIGITS.match(part)) and not _YEAR_ALONE.match(part)


def _doi(text: str) -> str | None:
    for m in _DOI.finditer(text):
        raw = re.sub(r"\s+", "", m.group(0))
        doi = _trim_identifier(raw)
        end = m.end()
        # Three shapes say the identifier was cut in half by a line break rather than ended: it
        # stops on a hyphen ("10.1007/978-3-030- 66534-0_2"), its suffix carries no digit at all
        # ("10.48550/arXiv. 2503.14713") or is too short to be one ("10.1007/s1 1219-009-9075-x"),
        # or the break fell on one of its own periods and digits follow ("10.1109/ICET.2017.
        # 8281704"). Either half is a DOI that resolves to nothing, or to another work -- the
        # front half of an ACM DOI is the proceedings volume -- which triage reads as a
        # fabrication signal. The join is made on the untrimmed match, so the separator the break
        # fell on survives.
        rest = _DOI_CONTINUES.match(text, end)
        if rest and (_looks_cut(doi) or _continues(raw, rest.group(1))):
            doi = _trim_identifier(raw + rest.group(1))
            end = rest.end()
        joined = _rejoin_underscore(doi, text, end)
        if joined != doi:
            doi = joined
        elif _looks_cut(doi):
            # Still cut and there is nothing to join it to: the entry carries no DOI this parser
            # can read. Emitting the near half would hand triage an identifier that resolves to
            # another work, which reads as signal (D) against a citation that never printed it.
            # `VERIFICATION-SPEC.md`: a field the entry does not carry is absent from the result.
            continue
        if len(_doi_suffix(doi)) >= 2:
            return doi
    return None


def _doi_suffix(doi: str) -> str:
    return doi.split("/", 1)[1] if "/" in doi else ""


_ARXIV_DOI = re.compile(rf"^10\.48550/arxiv\.({_ARXIV_NEW}|{_ARXIV_OLD})(v\d+)?$", re.I)
def _looks_cut(doi: str) -> bool:
    """Does this identifier stop mid-way rather than end?

    Four shapes say so: it ends on a hyphen, its suffix carries no digit, its suffix is one or
    two characters -- no publisher registers "s1", and "10.1007/s1 1219-009-9075-x" is a Springer
    article DOI broken after its second character -- or it registers an arXiv preprint under an
    identifier that is not one: "10.48550/arXiv.2411" is the front half of
    "10.48550/arXiv.2411.19043", and both halves carry digits."""
    if doi.endswith("-") or not any(c.isdigit() for c in _doi_suffix(doi)):
        return True
    if len(_doi_suffix(doi)) <= 2:
        return True
    return doi.lower().startswith("10.48550/arxiv.") and not _ARXIV_DOI.match(doi)


# A Springer chapter DOI is the book's ISBN plus the chapter's own number after an underscore
# ("10.1007/978-3-030-66534-0_2"), and an ACL one puts two underscores in ("10.1162/tacl_a_00335").
# pdftotext renders an underscore the line broke on as a space, so what survives is the book's DOI
# -- which resolves, to another work. It is only ever a break where the text actually continues:
# a bare ISBN suffix is also what a citation of the *whole book* correctly carries, and withholding
# those cost a real confirmation when this was written the other way round.
_ISBN_SUFFIX = re.compile(r"^97[89][\d-]+$")
# The far side of a dropped underscore: one to three short tokens, at least one carrying a digit,
# and no four-digit year (which is the entry's own date running on, not part of the identifier).
_UNDERSCORE_PARTS = re.compile(r"(?:\s+[0-9A-Za-z]{1,6}(?![0-9A-Za-z])){1,3}")


def _rejoin_underscore(doi: str, text: str, at: int) -> str:
    """`doi` with the tokens a dropped underscore separated from it, or `doi` unchanged."""
    if not (_ISBN_SUFFIX.match(_doi_suffix(doi)) or not any(c.isdigit() for c in _doi_suffix(doi))):
        return doi
    m = _UNDERSCORE_PARTS.match(text, at)
    if not m:
        return doi
    # `m.group(0)` rather than the groups: a repeated capture keeps only its last repetition, and
    # "tacl a 00335" needs both of its tokens.
    parts = m.group(0).split()
    if not parts or not any(any(c.isdigit() for c in p) for p in parts):
        return doi
    if any(re.fullmatch(r"(?:19|20)\d{2}", p) for p in parts):
        return doi
    return doi + "".join("_" + p for p in parts)


def _arxiv_id(text: str) -> str | None:
    m = _ARXIV.search(text)
    return m.group(1) if m else None


def _urls(text: str) -> list[str]:
    return [_trim_identifier(u) for u in _URL.findall(text)]


# ── author lists ─────────────────────────────────────────────────────────────

# Words that mark a segment as venue or title text rather than a list of people. A prefix carrying
# any of them is not an author list, however name-shaped its words are.
_NOT_AUTHORS = re.compile(
    r"\b(?:proc|proceedings|proceeding|conference|symposium|workshop|journal|transactions|"
    r"technical report|tech\. rep|arxiv|preprint|available|retrieved|accessed|http|www|"
    r"university press|edition|volume|chapter|abstract|isbn|issn)\b", re.I)

_ET_AL = re.compile(r"\bet\.?\s+al\.?", re.I)
# The role a name is listed in closes the list ("Bourque and Fairley, editors. Guide to ...").
_ROLE = re.compile(r"[,;]?\s*\b(?:editors?|eds\.?|ed\.|compilers?|translators?)\s*$", re.I)
# "et al." closes the author list; whatever follows it is the title.
_ET_AL_END = re.compile(r"\bet\.?\s+al\.?[.,]?\s+", re.I)
_SUFFIX = re.compile(r"^(?:jr|sr|ii|iii|iv)\.?$", re.I)
_ABBREVIATED_NAME = re.compile(r"^(?:jr|sr|ii|iii|iv|dr|prof|st|mr|ms|mrs|mohd)$", re.I)
# "C.", "C. E.", "CE", "M J" -- the given-name half of an inverted name. A lowercase letter counts
# only dotted and beside a capital: LaTeX abbreviates an accented given name to "J.ã.P." and
# pdftotext drops the tilde, so "Fernandes, J.a.P." read as two people, "Fernandes" and "J.a.P.".
_INITIALS_ONLY = re.compile(r"^(?=.*[A-Z])(?:[A-Z]\.?[\s-]*|[a-z]\.[\s-]*){1,4}$")
_HAS_DIGIT = re.compile(r"\d")
_HAS_LETTER = re.compile(r"[^\W\d_]")
# Software is cited under the account that publishes it, so a lone lowercase token is a name here
# even though it is not one anywhere else ("mity, "Use of uninitialized value ...", GitHub issue").
_HANDLE = re.compile(r"^[a-z][a-z0-9_.-]{1,30}$")
# A surname whose capital sits after an elided particle: "d'Amorim", "l'Ecuyer", "d\u2019Antoni".
_PARTICLE_CAP = re.compile(r"(?:^|\s)[a-z]{1,3}['\u2019][A-Z]")


def _periods_are_initials(name: str) -> bool:
    """Does every period in this candidate name belong to an initial, a shortened given name or a
    suffix?

    Any other period is a sentence boundary the author split ran past, which is how a title's
    first words end up glued to the last author ("Roy E Welsch. Regression diagnostics"). Two
    letters is the bar because bibliographies shorten given names to more than one ("Md. Fahim
    Arefin"), and because a surname long enough to be mistaken for one is longer than that."""
    for m in re.finditer(r"\.", name):
        token = re.split(r"[\s.\-]", name[:m.start()])[-1]
        if not ((0 < len(token) <= 2 and token.isalpha()) or _ABBREVIATED_NAME.match(token)):
            return False
    return True


def _looks_like_initials(chunk: str) -> bool:
    c = chunk.strip().rstrip(".")
    if not c:
        return False
    return bool(_INITIALS_ONLY.match(chunk.strip())) or (
        len(c) <= 3 and c.isupper() and c.isalpha())


def _name_like(chunk: str) -> bool:
    """Could this chunk be one person's name as a bibliography writes it?"""
    c = chunk.strip()
    if not c or _HAS_DIGIT.search(c) or _NOT_AUTHORS.search(c):
        return False
    if not _periods_are_initials(c):
        return False
    words = c.replace(".", " ").split()
    if not (1 <= len(words) <= 6):
        return False
    # Somewhere in a name there is a capitalised word or an initial; a run of lowercase words is
    # sentence text that a bad split left behind. A particle carrying the capital on its far side
    # counts -- `VERIFICATION-SPEC.md` names `d'Amorim`, and written surname-first it is the whole
    # chunk, so without this the entry reads as having no author list at all.
    return any(w[:1].isupper() for w in words) or bool(_PARTICLE_CAP.search(c))


def _merge_inverted(chunks: list[str]) -> list[str]:
    """Rejoin `Surname` + `I.` pairs that a comma split apart.

    `Wohlin, C., Runeson, P.` is one comma-separated list of two people, and `Claes Wohlin,
    Per Runeson` is one comma-separated list of two people; only the shape of the following chunk
    tells them apart. The joined form is kept as written -- every downstream comparison
    fingerprints names on initials and surname, so the order it is written in does not matter."""
    out: list[str] = []
    i = 0
    # Chicago inverts only its first author and writes the given name out ("Wohlin, Claes, Per
    # Runeson, and Martin Host"), so the pair is two single words where the rest are two-word
    # names. Without this the first person becomes two.
    lead_inverted = (len(chunks) >= 3 and len(chunks[0].split()) == 1 == len(chunks[1].split())
                     and any(len(c.split()) >= 2 for c in chunks[2:]))
    while i < len(chunks):
        cur = chunks[i]
        if i + 1 < len(chunks) and (i == 0 and lead_inverted):
            out.append(f"{cur}, {chunks[i + 1].strip()}")
            i += 2
        elif (i + 1 < len(chunks) and _looks_like_initials(chunks[i + 1])
              and not _looks_like_initials(cur)):
            out.append(f"{cur}, {chunks[i + 1].strip()}")
            i += 2
        elif out and _SUFFIX.match(cur):
            out[-1] = f"{out[-1]} {cur}"
            i += 1
        else:
            out.append(cur)
            i += 1
    return out


_SEPARATORS = re.compile(r"\s*(?:,|;|\band\b|&)\s*", re.I)
# A lowercase function word inside a byline says the byline is one organisation's name, not a list
# of people: "Institute of Electrical and Electronics Engineers", "Association for Computing
# Machinery". People\u2019s names do not carry one, so the `and` inside is part of the name.
_ORG_WORD = re.compile(r"(?:^|\s)(?:of|for|the|und|der|voor)(?:\s|$)")


def _is_organisation(segment: str) -> bool:
    """Is this whole byline the name of one body rather than a list of people?

    Only asked where it cannot be a list anyway: no comma to delimit one, and no initials, which is
    what every multi-author byline in the corpus carries. `&` counts when what precedes it is a
    single word, because "Barnes & Noble Research" is one publisher and "Wohlin & Runeson" would
    have been written with a comma or an "and"."""
    seg = segment.strip()
    if "," in seg or ";" in seg or re.search(r"\b[A-Z]\.", seg):
        return False
    # A body's name is short and is one sentence. Without both bounds this reads a whole
    # entry whose title happens to carry 'for' and 'and' as a single corporate author, and
    # the title then comes out of whatever is left -- one corpus reference lost its title
    # to exactly that.
    if len(seg.split()) > 8 or ". " in seg:
        return False
    if _ORG_WORD.search(seg) and re.search(r"\band\b", seg, re.I):
        return True
    return "&" in seg and len(seg.split("&", 1)[0].split()) == 1


def _split_names(segment: str) -> list[str]:
    """The people named in an author segment, in the order the entry lists them."""
    seg = _ET_AL.sub("", segment or "")
    seg = re.sub(r"\band\s+others\b", "", seg, flags=re.I)
    seg = _ROLE.sub("", seg).strip().strip(",;& ·")
    if not seg:
        return []
    # Strip the separators' own punctuation but not a trailing period: it is the initial's
    # ("Wohlin, C."), and dropping it loses the only mark that says the token is an initial.
    if _is_organisation(seg):
        return [seg]
    chunks = [c.strip().strip(",;").strip() for c in _SEPARATORS.split(seg)]
    chunks = [c for c in chunks if _HAS_LETTER.search(c)]
    names = [n.strip() for n in _merge_inverted(chunks) if n.strip()]
    return [n for n in names if _name_like(n) or _HANDLE.match(n)]


def _is_author_segment(segment: str) -> bool:
    """Does this prefix read as the entry's author list?"""
    seg = _ROLE.sub("", segment.strip()).strip()
    if not seg or len(seg) > 1200 or _NOT_AUTHORS.search(seg) or _HAS_DIGIT.search(seg):
        return False
    if _is_organisation(seg):
        return True
    if _ET_AL_END.search(seg):
        return False      # the list ended at "et al." and this segment runs past it
    chunks = [c.strip().strip(",;").strip() for c in _SEPARATORS.split(_ET_AL.sub("", seg))]
    # A stray mark between two names is punctuation the layout left behind ("OpenAI, :, Aaron
    # Hurst"), not a person, and holding the list to it disqualifies every real name in it.
    chunks = [c for c in chunks if _HAS_LETTER.search(c)]
    # Every chunk has to read as a name. Allowing a minority not to -- which would let a software
    # citation keep its account handles ("... Michael Davis, Ika, bfredl, narpfel ...") -- lets a
    # title whose comma-separated fragments are name-shaped be read as an author list instead, and
    # costs 20 corpus confirmations to recover one.
    return bool(chunks) and all(_name_like(c) or _looks_like_initials(c)
                                or _HANDLE.match(c) for c in chunks)


# ── venue detection ──────────────────────────────────────────────────────────

_VENUE_WORDS = re.compile(
    r"\b(?:in|proc|proceedings|conference|symposium|workshop|journal|transactions|magazine|"
    r"ieee|acm|springer|elsevier|wiley|usenix|press|arxiv|corr|preprint|technical report|"
    r"tech\. rep|thesis|dissertation|pp|vol|no\.|report|newsletter|letters|review|quarterly)\b",
    re.I)
_VOLUME_ISSUE = re.compile(r"\b\d{1,4}\s*[,(]\s*\d")
_PAREN_YEAR = re.compile(r"\((?:19|20)\d{2}[a-z]?\)")
# A journal's volume, issue and year, as Elsevier's numeric style writes them ("128 (4) (2002)")
# and as ACM's does ("30, 1 (2025)"), after a venue name that need not carry any word of the list
# above ("Psychological Bulletin", "Science", "Empirical Software Engineering"). No title is
# written that way.
_VOLUME_ISSUE_YEAR = re.compile(r"\b\d{1,4}\s*(?:\(\d{1,4}\)|,\s*\d{1,4})\s*\((?:19|20)\d{2}\)")


# A field that is only numbers: a page range, or a volume and issue.
_NUMBERS_ONLY = re.compile(r"^[\d\s,.:;()\-\u2010-\u2015]+$")


def _looks_like_venue(sentence: str) -> bool:
    """Is this the field that follows the title rather than more of the title?

    Only ever asked about one sentence at a time. Asked about a whole tail it would say yes to
    almost anything, since a citation's tail always names a venue eventually."""
    s = sentence.strip()
    if not s:
        return False
    if re.match(r"^(?:in|in:)\s", s, re.I):
        return True
    if _NUMBERS_ONLY.match(s):
        return True
    if _VOLUME_ISSUE_YEAR.search(s):
        return True
    return bool(_VENUE_WORDS.search(s)) and bool(
        _VOLUME_ISSUE.search(s) or _PAREN_YEAR.search(s) or _HAS_DIGIT.search(s))


# ── title extraction ─────────────────────────────────────────────────────────

# A period that ends an abbreviation, not a sentence. The hyphen admits the second half of a
# hyphenated initial ("K.-W. Chang", "J.-P. Katoen"), whose period read as a sentence end and left
# "Chang" as the title.
_ABBREV = re.compile(
    r"(?:^|[\s(\[.\-])(?:[A-Z]|proc|procs|vol|no|pp|ed|eds|edn|inc|ltd|co|dr|prof|sr|jr|st|mr|ms|"
    r"mrs|approx|fig|figs|tech|rep|univ|dept|dept|est|cf|vs|ch|sec|conf|int|intl|natl|assoc|"
    r"soc|syst|eng|sci|comput|trans|j|e\.g|i\.e|al|etc|nos|art|no|md|mohd|"
    r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec|"
    # The words a journal name is abbreviated to. Without them a citation's venue reads as several
    # sentences ("IEEE Trans. Dependable Secur. Comput.") and the first of them, being short and
    # digit-free, does not look like a venue at all.
    r"softw|secur|depend|technol|inf|appl|autom|netw|intell|commun|manag|pract|archit|evol|"
    r"empir|mag|rev|lett|res|sect|meth|methodol|softwr|electron|robot|educ|med|biol|phys|"
    r"chem|math|stat|psychol|ergon|hum|mach|learn|artif)\.$", re.I)


# A period with a digit on each side of it: a version number the layout broke ("Deepseek-v3. 2",
# "Qwen2. 5-coder"). A venue that opens with a year is the other way round, a letter then a digit,
# and that one does end the title ("... vulnerabilities. 2006 IEEE Symposium on ...").
_SPLIT_VERSION = re.compile(r"\d\.\s+\d")
# A title that opens with its own number, as the Royal Society printed them: "VII. Note on
# regression and inheritance in the case of two parents" is one title, and CrossRef records it
# with the numeral. Only a numeral that is the whole of the sentence so far counts, so a name
# suffix ("John Smith III. A title.") still ends the author sentence.
_ROMAN_HEAD = re.compile(r"^[IVXLC]{2,6}\.$")


def _sentence_end(text: str, start: int = 0) -> int:
    """Index just past the first sentence-ending period, or len(text)."""
    i = start
    while True:
        m = re.compile(r"\.(?=\s)").search(text, i)
        if m is None:
            return len(text)
        head = text[:m.end()]
        if (_ABBREV.search(head) or _SPLIT_VERSION.match(text, m.start() - 1)
                or _ROMAN_HEAD.match(text[start:m.end()].lstrip())):
            i = m.end()
            continue
        return m.end()


# How many marks of each kind are worth examining. A title asks one question, and an entry quotes
# one title; a segmentation slip is what produces hundreds, and scanning those is quadratic in the
# length of an entry that was never a reference to begin with.
_SCAN_LIMIT = 12


def _question_end(text: str) -> int | None:
    """Index just past a `?` or `!` that ends the title, or None.

    Titles ask questions, so the mark alone decides nothing: it ends the title only when the
    sentence after it is the venue."""
    for m in list(re.finditer(r"[?!](?=\s)", text))[:_SCAN_LIMIT]:
        rest = text[m.end():].strip()
        if not rest:
            continue
        nxt = _TRAILING_IN_VENUE.sub("", rest[:_sentence_end(rest)])
        # Up to the next mark, and short of Elsevier's ", in:". In the styles that join the venue
        # to the title with a comma, the sentence after "Hey!" is "are you committing tangled
        # changes? In Proceedings of ..., 2014", and the one after "Twins or false friends?" is
        # "a study on energy consumption ..., in: 2023 IEEE/ACM 45th ..."; both read as a venue
        # and cut the title to its question.
        nm = re.search(r"[?!](?=\s)", nxt)
        if nm:
            nxt = nxt[:nm.end()]
        if _looks_like_venue(nxt.rstrip(". ")):
            return m.end()
    return None


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) > 1 and s[0] in _OPEN_Q and s[-1] in _CLOSE_Q:
        s = s[1:-1]
    # IEEE puts the entry's comma inside the closing quote: `"Title," in Proc.`
    return s.strip().rstrip(",")


class _Quoted:
    """One quoted span: `.start()`, `.end()` and `.group(1)`, like a match object.

    Written by hand rather than as a regex because choosing the closing mark takes a rule a regex
    cannot express. IEEE closes its title quote on the entry's own comma (`"Title," in Proc.`), so
    where several closing marks are available the one carrying that comma is the title's -- which
    is what keeps a title that quotes something ("Just enough ... just for "me": Fundamental
    principles ...") from being cut at the quotation it contains."""

    def __init__(self, text: str, s: int, e: int, inner: str, closed_on: str):
        self._s, self._e, self._inner = s, e, inner
        # The character the closing mark sits on. IEEE tucks the entry's own comma inside it, and
        # that comma is what says the quotes delimit the whole title.
        self.closed_on = closed_on

    def start(self) -> int:
        return self._s

    def end(self) -> int:
        return self._e

    def group(self, n: int = 0) -> str:
        return self._inner


def _find_quoted(text: str, at_start: bool = False) -> _Quoted | None:
    opened = 0
    for i, ch in enumerate(text):
        if ch not in _QUOTE_PAIRS:
            continue
        if at_start and i:
            return None
        opened += 1
        if opened > _SCAN_LIMIT:
            return None
        closers = _QUOTE_PAIRS[ch]
        ends = [j for j in range(i + 1, len(text)) if text[j] in closers]
        if not ends:
            continue
        end = next((j for j in ends if text[j - 1] in ",."), ends[0])
        inner = text[i + 1:end].strip()
        if inner:
            return _Quoted(text, i, end + 1, inner, text[end - 1])
        return None
    return None


def _title_from(rest: str) -> str:
    """The title at the head of the post-author remainder."""
    rest = rest.strip()
    if not rest:
        return ""
    if rest[0] in _OPEN_Q:
        m = _find_quoted(rest, at_start=True)
        if m:
            after = rest[m.end():].lstrip()
            # The quotes delimit the whole title where IEEE style says so -- it tucks the entry's
            # own comma inside the closing mark -- or where a venue follows them. A title may
            # instead open with a quotation and run on: `"Why Should I Trust You?": Explaining the
            # Predictions of Any Classifier`, `"How Was Your Weekend?" Software Development Teams
            # Working From Home`. Reading only the quoted half of those loses the words that
            # identify the paper.
            # The sentence after the quote is tested up to a ", in:" -- Elsevier joins the venue
            # to the title with a comma, and `"safety automata" - A new specification language
            # ..., in: Proceedings of ...` read as a quoted title followed by a venue.
            nxt = _TRAILING_IN_VENUE.sub("", after[:_sentence_end(after)]).rstrip(". ")
            if not after or m.closed_on in ",." or _looks_like_venue(nxt):
                return _clean_title(m.group(1))
    q = _question_end(rest)
    end = _sentence_end(rest)
    if q is not None and q < end:
        end = q
    title = rest[:end]
    if title[:1] in _OPEN_Q:
        q = _find_quoted(title, at_start=True)
        if q:
            title = title[:q.start()] + q.group(1) + title[q.end():]
    return _clean_title(title)


# Springer labels the address it prints ("Podman. URL https://podman.io/"), and the label goes
# with it: eleven corpus references parsed to the title "URL".
_TRAILING_IDENT = re.compile(
    r"(?:\s*[,.;:]\s*)?(?:doi\s*:|(?:\burl\s+)?https?://|arxiv\s*:).*$", re.I)
# An access note. It only counts as one where a field starts, because every one of these words is
# also an ordinary word: "the readily available tests" is a title, and so is "Online impact
# analysis". "Online" is only recognised in the brackets the styles print it in.
_TRAILING_NOTE = re.compile(
    r"(?:\s*[,.;:]\s*(?:available|retrieved|accessed)\b"
    r"|\s*[\[(]\s*online\b"
    r"|^(?:available|retrieved|accessed)\b\s*(?::|from\b|at\b|on\b|$)).*$", re.I)


# A comma-delimited field that a title can end with only because the entry's date or volume ran
# on into the same sentence ("... in LLM-generated code, 2026.", "Experimentation in software
# engineering, volume 236.").
_MONTH = (r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|"
          r"june|july|august|september|october|november|december")
_TRAILING_FIELD = re.compile(
    rf",\s*(?:(?:(?:{_MONTH})\.?\s+)?(?:19|20)\d{{2}}[a-z]?"
    r"|(?:volume|vol\.?|number|no\.?|issue|edition|ed\.?|pages?|pp\.?)\s*[\dIVXivx]+[^,]*"
    r"|\d+(?:st|nd|rd|th)\s+ed(?:ition)?\.?)$", re.I)


# What an entry appends to its title in parentheses and the record does not carry: the year, the
# conference's own acronym ("(DIS '25)", "(CHEOPS '21)"), an edition.
_TRAILING_PAREN = re.compile(
    r"\s*\((?:(?:19|20)\d{2}[a-z]?"
    r"|[A-Z][A-Za-z/&-]{1,14}\s*[\u2018\u2019']?\d{2,4}"
    r"|\d+(?:st|nd|rd|th)?\s*ed(?:ition|n)?\.?)\)$", re.I)


# Elsevier's Harvard style joins the venue to the title with a comma rather than a period ("Coca:
# Improving and explaining ... detection systems, in: Proceedings of the IEEE/ACM 46th ..."), so no
# sentence break separates them and the venue was read as part of the title. "in:" opens no title
# of its own.
_TRAILING_IN_VENUE = re.compile(r",\s+in:\s.*$", re.I)


def _clean_title(t: str) -> str:
    t = _TRAILING_NOTE.sub("", _TRAILING_IDENT.sub("", t.strip()))
    t = _TRAILING_IN_VENUE.sub("", t)
    t = t.strip().strip(",;: ")
    if t.endswith(".") and not _ABBREV.search(t):
        t = t[:-1]
    t = _TRAILING_FIELD.sub("", t.strip())
    # A parenthesis the entry printed after its title, with no comma to mark the field: a year
    # ("... unreproducible builds in java (2025)"), a conference acronym ("... Procedural Palette
    # (DIS '25)"), an edition ("... for the Behavioral Sciences (2 ed.)").
    t = _TRAILING_PAREN.sub("", t.strip())
    return _strip_quotes(t).strip()


# ── entry segmentation ───────────────────────────────────────────────────────

_REPEAT_AUTHORS = re.compile(r"^[-‐-―_]{2,}\s*[.,:]?\s*")
# ACM prints "[n. d.]" where a dated entry prints its year, and it plays the same structural part.
_NO_DATE = r"\[\s*n\.?\s*d\.?\s*\]"
# The bound on the author half is generous because author lists are: a self-adaptive-systems
# roadmap carries 30 names and 500 characters before its year, and a bound that cuts short of that
# reads the whole list as a title.
_YEAR_FIRST = re.compile(
    rf"^(.{{2,1200}}?)[.,]\s+(?:\(?((?:19|20)\d{{2}}[a-z]?)\)?|{_NO_DATE})[.,]\s+(.+)$")
_YEAR_PAREN = re.compile(r"^(.{2,1200}?)\s*\(((?:19|20)\d{2}[a-z]?)\)\.?\s*(.+)$")
_COLON_LIST = re.compile(r"^([^:]{3,400}):\s+(.+)$")
# A date field the entry has already used, at the head of what is left. It has to carry its own
# punctuation or parentheses: a bare four-digit number opening a title belongs to the title
# ("2025 State of AI-Assisted Software Development").
_LEADING_DATE = re.compile(
    rf"^(?:\((?:19|20)\d{{2}}[a-z]?\)|(?:(?:{_MONTH})\.?\s+)?(?:19|20)\d{{2}}[a-z]?[.,]"
    rf"|{_NO_DATE}\.?)\s*", re.I)
# IEEE prints books and reports without quotation marks: initials-led names, then the title, then
# the edition and the publisher, all comma-delimited.
# The initials may be hyphenated ("K.-W. Chang", "J.-P. Katoen"); without the hyphen the last
# author of "..., B. Ray, and K.-W. Chang. Unified pre-training ..." was read as the title "and K.-W".
_INITIALS_LED = re.compile(r"^(?:and\s+)?[A-Z]\.(?:\s*-?\s*[A-Z]\.)*\s+\S")
# The role that follows the names, at the head of what is left after them ("..., and
# T. Zimmermann, editors. Recommendation Systems in Software Engineering"). Editors only, with the
# period or comma the role is written with: "Editor wars" opens a title, and so does "Compilers:
# Principles, Techniques, and Tools", which the role "compilers" read off the Dragon Book.
_LEADING_ROLE = re.compile(r"^(?:editors?[.,]|eds?\.,?)\s+", re.I)
# The order the medical styles print and `VERIFICATION-SPEC.md` names beside the inverted one:
# "Wohlin C, Runeson P, Host M. Experimentation in software engineering." Its last initial ends the
# author list with a period that reads exactly like an initial's, so no sentence rule can find the
# boundary; the shape of the whole run is what marks it. At least one comma has to fall inside the
# run, or "Thomas G. Dietterich. Approximate statistical tests ..." reads its own surname as a
# title.
_NAME = r"[A-Z][^\W\d_][\w'\u2019-]*"
_SURNAME_INITIALS = re.compile(
    rf"^((?:{_NAME}(?:\s+{_NAME})*\s+[A-Z]{{1,4}},\s+(?:and\s+)?){{1,15}}"
    rf"{_NAME}(?:\s+{_NAME})*\s+[A-Z]{{1,4}})\.\s+(.+)$")
# What makes a leading phrase a list of people rather than a title: a separator, or an initial.
_AUTHOR_LIST = re.compile(r",|\s(?:and|&)\s|\b[A-Z]\.")
# A field only a venue carries, recognised at its head. Narrower than `_looks_like_venue` on
# purpose: that one weighs a word list, and a title is allowed to say "review" or "letters"
# ("Statistics review 6: Nonparametric methods"), to open with "In" ("In Search of Socio-Technical
# Congruence"), and to number an issue it is about ("triage of issue 500 reports").
_VENUE_FIELD = re.compile(
    r"^(?:in\b[^.]{0,80}?\b(?:proc|proceedings|conference|symposium|workshop|journal)\b"
    r"|(?:volume|vol\.?|no\.?|issue|pp\.?|pages)\s*\d)", re.I)
# The comma-delimited field that follows the title in that style.
_AFTER_TITLE = re.compile(r"^(?:\d+(?:st|nd|rd|th)\s+ed|eds?\.|edition|(?:19|20)\d{2}\b|"
                          r"pp?\.|vols?\.|nos?\.)", re.I)


def _has_inverted_name(chunks: list[str]) -> bool:
    """Is this list written surname-first (`Wohlin, C., Runeson, P.`)?

    It is the only thing that separates a Springer entry, whose colon ends the author list, from
    an IEEE one, whose colon is the title's own subtitle mark."""
    return any(_looks_like_initials(b) and not _looks_like_initials(a)
               for a, b in zip(chunks, chunks[1:]))


def _ieee_comma_split(text: str) -> tuple[str, str] | None:
    """(author segment, remainder) for IEEE's unquoted comma style, or None.

    `V. Barnett and T. Lewis, Outliers in Statistical Data, 3rd ed. Wiley, 1994.` -- the author
    list is the leading run of comma-separated fields that open with an initial, and the title is
    the field after it."""
    fields = text.split(", ")
    taken = 0
    while taken < len(fields) and _INITIALS_LED.match(fields[taken]):
        taken += 1
    if not taken or taken >= len(fields):
        return None
    rest = _LEADING_ROLE.sub("", ", ".join(fields[taken:]))
    if not rest.strip():
        return None
    return ", ".join(fields[:taken]), rest


# A comma field that is a publisher or a preprint server and nothing else ("Springer", "SSRN",
# "Wiley-Interscience", "Addison-Wesley Professional", "Tech. rep."): the field after a title in
# the comma-delimited styles, with no digit for `_looks_like_venue` to key on. The names are the
# ones the corpus prints there.
_BARE_VENUE = re.compile(
    r"^(?:springer|elsevier|wiley|addison-wesley|ieee|acm|usenix|arxiv|ssrn|corr|"
    r"tech\.?\s*rep\.?)\b[^,\d]{0,30}$", re.I)


def _cut_at_trailing_field(rest: str) -> str:
    """`rest` truncated before the comma-delimited field that follows a title.

    Only sound where the style delimits its fields with commas, so it is used on the IEEE comma
    reading and on an "et al." that a comma follows; a title that carries a comma of its own would
    otherwise lose everything after it."""
    fields = rest.split(", ")
    for i in range(1, len(fields)):
        tail = fields[i]
        if (_AFTER_TITLE.match(tail) or _BARE_VENUE.match(tail)
                or _looks_like_venue(tail[:_sentence_end(tail)])):
            return ", ".join(fields[:i])
    return rest


def _leading_names(text: str) -> tuple[str, str] | None:
    """(author segment, remainder) for an entry whose first sentence is its author list.

    The last reading tried, and the only one with no mark to key on: `Martin Fowler. Refactoring:
    improving the design of existing code. Addison-Wesley, 2018.` and `Deep Learning. MIT Press,
    2016.` are the same shape and mean different things. Four things have to hold together, since
    no one of them separates the two:

    * the opening reads as names, and is more than a single word -- unless the entry is a web
      resource, which names its author in one ("Anthropic. Permission modes. https://...");
    * what follows yields a title at all;
    * that title is not itself a venue ("Springer Journal, volume 25");
    * and either a field follows the title, or the title is long enough to be one. This is where
      `Deep Learning` fails: all its entry has left is a publisher and a year.
    """
    end = _sentence_end(text)
    if end >= len(text):
        return None
    head, tail = text[:end - 1].strip(), text[end:].strip()
    web = "http" in text.lower()
    if not _is_author_segment(head) or not (web or len(head.split()) >= 2
                                            or _AUTHOR_LIST.search(head)):
        return None
    title = _title_from(tail)
    if not title or _VENUE_FIELD.search(title):
        return None
    if _sentence_end(tail) < len(tail) or len(title.split()) >= 3 or web:
        return head, tail
    return None


def _candidates(text: str, prev_authors: list[str] | None):
    """Every (authors, remainder) reading of the entry, best first.

    Each style is recognised by the mark that separates its author list from its title -- a
    standalone year, an "et al.", an opening quote, a colon after inverted names, a comma after
    initials-led ones -- and the readings are tried in that order. `parse_reference` takes the
    first that yields a title, so a mark that happens to appear inside a venue cannot leave the
    entry unparsed."""
    m = _REPEAT_AUTHORS.match(text)
    if m:
        yield list(prev_authors or []), _LEADING_DATE.sub("", text[m.end():])
        return

    for pattern in (_YEAR_FIRST, _YEAR_PAREN):
        m = pattern.match(text)
        if m and _is_author_segment(m.group(1)):
            yield _split_names(m.group(1)), m.group(3)

    # "et al." ends the author list wherever it falls, including in the styles that print no year
    # next to the names ("... Chetan Rane, et al. Swe-bench pro: Can AI agents ...").
    m = _ET_AL_END.search(text)
    if m and _is_author_segment(text[:m.start()]):
        rest = _LEADING_DATE.sub("", text[m.end():])
        # A comma after the "et al." says the entry delimits its fields with commas, so the venue
        # is the comma field after the title ("..., et al., A prompt pattern catalog ..., arXiv
        # preprint arXiv:2302.11382") and the IEEE comma reading's cut applies. A quoted title
        # marks its own end and is left alone.
        if m.group(0).rstrip().endswith(",") and rest[:1] not in _OPEN_Q:
            rest = _cut_at_trailing_field(rest)
        yield _split_names(text[:m.start()]), rest

    # A quoted title marks its own boundary, so whatever precedes it is the author list -- but only
    # where the quote opens a field. A title may quote a word of its own ("The "Goodness" of Code
    # Reviews"), and reading that quote as the boundary keeps one word of the title and turns the
    # words before it into an author.
    m = _find_quoted(text)
    if (m and m.group(1).split() and text[:m.start()].rstrip().endswith((",", ".", ":", ";"))
            and _is_author_segment(text[:m.start()].rstrip(" ,"))):
        yield _split_names(text[:m.start()]), text[m.start():]

    # Springer's inverted list ends at a colon. Two guards keep an ordinary subtitle out: the colon
    # has to come before the entry's first sentence break, and the names before it have to be
    # written surname-first.
    m = _COLON_LIST.match(text)
    if m and _sentence_end(m.group(1)) >= len(m.group(1)) and _is_author_segment(m.group(1)):
        chunks = _split_names(m.group(1))
        if _has_inverted_name([c.strip() for c in _SEPARATORS.split(m.group(1)) if c.strip()]):
            yield chunks, m.group(2)

    m = _SURNAME_INITIALS.match(text)
    if m and _is_author_segment(m.group(1)):
        yield _split_names(m.group(1)), _LEADING_DATE.sub("", m.group(2))

    split = _ieee_comma_split(text)
    if split and _is_author_segment(split[0]):
        yield _split_names(split[0]), _cut_at_trailing_field(split[1])

    split = _leading_names(text)
    if split:
        yield _split_names(split[0]), _LEADING_DATE.sub("", split[1])

    # An entry with no author at all still opens with its own date often enough to matter
    # ("2025. WebAssembly Design Rationale. https://...").
    yield [], _LEADING_DATE.sub("", text)


_WORDS = re.compile(r"[^\W\d_]{2,}")
# The only words a page range or a volume field carries.
_BIBLIOGRAPHIC = re.compile(r"^(?:pp|vol|no|nos|eds?|edn|art|iss)$", re.I)


def _is_title(title: str) -> bool:
    """Is there a title here at all?

    A page range, a bracketed label or a licence footer that a segmentation slip left behind is not
    a reference, and saying so lets the audit record it as `unparsed` -- which tells a triager to
    look at the PDF -- instead of reporting a work that does not exist. A tool's name is a title
    even at two letters ("Ck"), so the bar is a word, not a length."""
    return any(not _BIBLIOGRAPHIC.match(w) for w in _WORDS.findall(title or ""))


def parse_reference(text: str, prev_authors: list[str] | None = None) -> Reference | None:
    """One bibliography entry to its fields, or None when no title can be read out of it."""
    raw = text or ""
    cleaned = _clean(raw)
    if not cleaned:
        return None
    for authors, rest in _candidates(cleaned, prev_authors):
        title = _title_from(rest)
        if _is_title(title):
            return Reference(title=title, authors=authors, doi=_doi(cleaned),
                             arxiv_id=_arxiv_id(cleaned), urls=_urls(cleaned), raw_citation=raw)
    return None
