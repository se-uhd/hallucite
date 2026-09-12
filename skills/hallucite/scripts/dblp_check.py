"""The offline DBLP check: does the mirror hold the work this citation names?

DBLP decides most of hallucite's confirmations, so this is `verifier`'s first backend, and it is
also the second opinion the audit runs over whatever the external verifier missed. Both ask the
same question of the same SQLite file, over *all* records sharing the cited title rather than the
one an FTS query happens to rank first -- "Experimentation in Software Engineering" is three book
editions, a 1986 TSE article, a 1997 survey and a 2008 conference paper, and comparing a citation
against whichever comes back first is how a real work gets reported missing.

Retrieval is generous and the decision is strict, which is what lets the two be tuned separately.
Retrieval asks four phrase queries -- both readings of a hyphen, both foldings of a stroked letter
-- and a word-wise AND that needs neither reading to be right for the whole title. The decision
then takes only records whose title matches the cited one letter for letter once case, spacing and
punctuation are gone, never a similarity score, and confirms one only if every cited name that
reads as a person is matched by an author of that record.

That last rule is the one that matters most, and it is asymmetric on purpose. A citation may name
fewer authors than the record: that is what "et al." means. A citation that names *more* is either
a mistake or the fabrication this tool exists to catch -- an invented author constellation spliced
onto a real paper, where title, venue and pages are all correct and nothing else gives it away.
Measured over 250 real DBLP records, appending one invented name was confirmed 250 times out of
250 under the rule this replaced.

Written from the database schema alone (4 tables + an FTS5 index); no hallucinator code involved.
"""

from __future__ import annotations

import functools
import os
import re
import sqlite3
import unicodedata
from dataclasses import dataclass

# Titles with fewer FTS tokens than this are too generic for a phrase query to be meaningful
# ("Design Rules" would sweep in every same-phrase record); leave those to triage.
_MIN_TOKENS = 3
# A ceiling on how many FTS hits are examined, not a relevance cut: SQLite returns them in row
# order, so a low cap drops the record a citation names for no reason but its position in the
# index. Over the corpus, 3 of 1,478 confirmed references are confirmed by a record their query
# returns past row 50, one of them at row 2,507. The strict title comparison below is what narrows
# the rows; this only stops a generic title from scanning the whole index.
_MAX_CANDIDATES = 20000


@dataclass
class SecondOpinion:
    key: str                 # DBLP record key, e.g. "books/daglib/0029933"
    title: str               # the candidate's title as stored
    authors: list[str]       # the candidate's full author list
    # Record metadata, when the mirror was built by an ingest that stores it. A mirror holding only
    # key/title/authors leaves these None, and everything here keeps working.
    year: int | None = None
    venue: str | None = None
    ee: str | None = None    # electronic edition, usually the DOI
    kind: str | None = None  # "article", "inproceedings", "book", ...


# Letters with a stroke or bar carry no combining mark, so NFKD leaves them; without this map
# 'Przybyłek' and 'Przybylek' are different people. Now that the mirror actually holds accented
# names, this is the difference between confirming a reference and sending it to triage.
_LETTER_FOLD = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ð": "d", "Ð": "D",
    "ħ": "h", "Ħ": "H", "ı": "i", "İ": "I", "ŀ": "l", "Ŀ": "L", "ŧ": "t", "Ŧ": "T",
    "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ß": "ss", "ẞ": "SS", "þ": "th", "Þ": "TH",
})


def _fold(s: str) -> str:
    """Lowercase and strip diacritics, so 'Höst'/'Wesslén'/'Przybyłek' compare against ASCII."""
    nfkd = unicodedata.normalize("NFKD", s.translate(_LETTER_FOLD))
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _extra_columns(con) -> list[str]:
    """Which of the record-metadata columns this mirror has. A database built before the ingest
    stored them has none, and the second opinion still works on title and authors alone."""
    try:
        have = {r[1] for r in con.execute("PRAGMA table_info(publications)")}
    except sqlite3.Error:
        return []
    return [c for c in ("year", "venue", "ee", "kind", "volume", "number", "pages")
            if c in have]


# A subtitle mark: a colon, a dash used as one, or an em/en dash.
_SUBTITLE = re.compile(r"\s*[:\u2013\u2014]\s*|\s+-\s+")


def _letters(t: str) -> str:
    """A title reduced to its letters and digits, so hyphenation, spacing and punctuation cannot
    separate two spellings of it: a suspended hyphen ("Player- and Data-Driven"), a compound
    written open ("Model Driven" for "Model-Driven"), a line break inside a word."""
    return re.sub(r"[^a-z0-9]", "", _fold(t or ""))


def _subtitle_head(t: str) -> str:
    """The title up to its subtitle mark, or "" when it carries none or the part before it is too
    short to identify a work on its own."""
    head = _SUBTITLE.split(t or "", maxsplit=1)[0]
    letters = _letters(head)
    # Long enough to name a work on its own. "AI: A Survey" leaves "AI", which names nothing.
    return letters if head != (t or "") and len(head.split()) >= 2 and len(letters) >= 12 else ""


# The edition DBLP appends to a book's title, in the two shapes it uses: "(2. ed.)" and ", 3rd
# Edition". A citation names the work and the parser already trims the edition it prints
# (`_TRAILING_PAREN`); the record's has to come off too, or "The mythical man-month" is not the
# book the mirror holds.
_EDITION_SUFFIX = re.compile(
    r"\s*(?:\(\s*\d+(?:st|nd|rd|th)?\.?\s*ed(?:ition|n)?\.?\s*\)"
    r"|,\s*(?:\d+(?:st|nd|rd|th)|second|third|fourth|fifth)\s+ed(?:ition|n)?\.?)\s*\.?$", re.I)


def titles_match(cited: str, candidate: str) -> bool:
    """Are these the same title?

    Compared on letters alone, and a subtitle is allowed to be present on one side only -- but only
    against the *whole* of the other side. Comparing two heads would make "Large Language Models: A
    Survey" and "Large Language Models: An Empirical Study" the same work. An edition suffix on the
    record is not part of the title."""
    candidate = _EDITION_SUFFIX.sub("", candidate or "")
    cited_all, candidate_all = _letters(cited), _letters(candidate)
    if not cited_all or not candidate_all:
        return False
    if cited_all == candidate_all:
        return True
    return _subtitle_head(cited) == candidate_all or _subtitle_head(candidate) == cited_all


def normalized_title(t: str) -> str:
    """A title reduced to what two spellings of it have in common: case, punctuation, diacritics,
    hyphens and repeated whitespace removed. Every title comparison in hallucite goes through
    this, so a record found by one backend and a record found by another are judged alike."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", _fold(t or "").replace("-", ""))).strip()


def _name_parts(name: str) -> tuple[set[str], set[str]]:
    """(name words, initials) of one author string, in any of the conventions bibliographies use:
    'Claes Wohlin', 'Wohlin C', 'Wohlin, C.', 'de Dieu MJ', 'V. Richard Benjamins'. A token of
    1-4 capitals is an initials run ('MJ' -> m, j); anything longer is a name word."""
    words: set[str] = set()
    initials: set[str] = set()
    # DBLP writes an alias in parentheses ("Tse-Hsun (Peter) Chen"); the parentheses are not part
    # of the name, and left in place they kept "Peter" from pairing with it.
    tokens = re.split(r"[\s.,]+", name.replace("(", " ").replace(")", " "))
    for i, tok in enumerate(tokens):
        if not tok or tok.isdigit():
            continue  # digits: DBLP homonym suffixes ("Thomas Zimmermann 0001")
        folded = _fold(tok)
        # "et al." is not a name -- but "Al" on its own is one, and 3,999 DBLP authors carry it
        # ("Fahmid Al Rifat"), so it is only dropped where an "et" precedes it. A generational
        # suffix is not a name either, and one side carries it as often as not.
        if folded in ("others", "et", "jr", "sr", "ii", "iii", "iv") or (
                folded == "al" and i and _fold(tokens[i - 1]) == "et"):
            continue
        if (len(tok) <= 4 and tok.isalpha() and tok[0].isupper()
                and sum(c.isupper() for c in tok) >= min(2, len(tok))):
            # An initials run: "MJ", "C", also mixed-case with a particle letter ("CEdC" for
            # "Carlos Eduardo de Carvalho"). Only the capitals are initials.
            initials.update(_fold(c) for c in tok if c.isupper())
        elif len(tok) == 1:
            initials.add(_fold(tok))
        else:
            # An apostrophe is written three ways and stored a fourth, so it is dropped rather
            # than compared: "O\u2019Donoghue" and "O'Donoghue" are one surname, and "d\u2019Amorim"
            # and "d'Amorim" are one more.
            words.update(_fold(w).replace("'", "") for w in _APOSTROPHE.sub("'", tok).split("-")
                         if w)
    return words, initials


_APOSTROPHE = re.compile(r"[\u2018\u2019\u02bc`\u00b4]")
# The particle a surname elides onto its front, which a citation is as likely to drop as to keep.
_ELIDED = re.compile(r"(?<![^\W\d_])[a-zA-Z]{1,2}['\u2018\u2019](?=[A-Za-z])")
_ESZETT_AS_B = re.compile(r"(?<=[a-z])B(?=[a-z])")
_UMLAUT = re.compile(r"[äöüÄÖÜ]")
_UMLAUT_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue",
                                  "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def _name_readings(name: str):
    """The name's parts under each reading of a hyphen it carries.

    A surname broken across a line keeps its hyphen ("Poshy-vanyk", "Diet-mar") and a real compound
    carries one of its own ("Kolahdouz-Rahimi", "Xuan-Son"); nothing in the string says which. The
    wrong reading simply fails to match, so both are asked, and so is the reading in which a
    capital B is an eszett the PDF could not render."""
    yield _name_parts(name)
    if "-" in name:
        yield _name_parts(name.replace("-", ""))
    # An eszett a PDF renders as a capital B, which pdftotext has no way to know: "Leßenich" comes
    # out "LeBenich". Only ever an extra reading, so a name that really carries a B ("JetBrains")
    # keeps the one it had.
    if _ESZETT_AS_B.search(name):
        yield _name_parts(_ESZETT_AS_B.sub("ss", name))
    # A citation may drop the elided particle a surname carries: "Marcelo Amorim" for "Marcelo
    # d'Amorim", "Anne Hoekstra" for "Anne 't Hoekstra". The given name still has to pair, so this
    # widens the surname and not the person.
    if _ELIDED.search(name):
        yield _name_parts(_ELIDED.sub("", name))
    # The German transliteration of an umlaut, which a citation carries where its style or its
    # author's keyboard could not write the letter: "Buettcher" for "Büttcher", "Juergens" for
    # "Jürgens". Read off the side that carries the umlaut, so only a name that really has one
    # gains the second spelling; contracting "ue" in every name instead would rewrite "Miguel"
    # and "Rodriguez" into spellings an invented author could hide behind.
    composed = unicodedata.normalize("NFC", name)
    if _UMLAUT.search(composed):
        yield _name_parts(composed.translate(_UMLAUT_TRANSLIT))


def _author_matches(cited: str, candidate: str) -> bool:
    """Does the cited author name plausibly denote the candidate author?

    The two names have to share a name word -- a surname, in any order either side writes it -- and
    everything else about them has to be pairable: an initial with a name it begins, a name with an
    initial that begins it, a name with itself. What is left over on the *shorter* side is what a
    record or a citation simply does not carry, and is allowed; what is left over while the other
    side still has a part is a contradiction.

    That is what keeps `J. Smith` and `Alice Smith` apart while letting `Emiliano De Cristofaro`
    answer to `Cristofaro, E.` -- the particle has nothing to contradict once the initial is
    spoken for -- and letting `C. E. Jimenez` be `Carlos Jimenez`, whose record carries no middle
    name for the `E.` to disagree with."""
    for cw, ci in _name_readings(cited):
        for dw, di in _name_readings(candidate):
            shared = cw & dw
            if not shared:
                continue
            parts = sorted(cw - shared) + sorted(ci)
            slots = sorted(dw - shared) + sorted(di)
            if _max_pairs(parts, slots) == min(len(parts), len(slots)):
                return True
    return False


def _pairs_with(part: str, slot: str) -> bool:
    return part == slot or slot.startswith(part) or part.startswith(slot)


def _max_pairs(parts: list[str], slots: list[str]) -> int:
    """How many of these name parts can be paired with distinct slots. Both lists are a handful of
    tokens, so the exhaustive answer is cheaper than reasoning about which greedy order is safe."""
    if not parts or not slots:
        return 0
    best = _max_pairs(parts[1:], slots)
    for i, slot in enumerate(slots):
        if _pairs_with(parts[0], slot):
            best = max(best, 1 + _max_pairs(parts[1:], slots[:i] + slots[i + 1:]))
    return best


# Text a reference parser can leave in an author list that is not a person: a venue fragment, a
# page range, a bracketed acronym. Held against a real name it would refute every citation it
# appears in, so it is not held against one -- but the list is kept short, because every word on it
# is a name an invented author could hide behind.
_NOT_ANY_NAME = re.compile(r"\d|[()\[\]]")
_VENUE_WORD = re.compile(
    r"\b(?:proc|proceedings|conference|symposium|workshop|journal|transactions|"
    r"press|arxiv|preprint|university|institute|editors?|eds?)\b", re.I)
# DBLP tells two people of the same name apart with a trailing number ("Thomas Zimmermann 0001").
_HOMONYM_SUFFIX = re.compile(r"\s+\d{4}$")


def _is_person(name: str) -> bool:
    """Does this entry of a parsed author list name a person?

    A venue fragment held against a real name would refute every citation it appears in. The bar is
    kept low on purpose, because every name this skips is one an invented author could hide behind:
    a venue word alone is not enough, since "John Press" and "Anne Institute" are people, and it
    counts only alongside the length of a venue."""
    n = _HOMONYM_SUFFIX.sub("", (name or "").strip())
    if not n or _NOT_ANY_NAME.search(n):
        return False
    return not (_VENUE_WORD.search(n) and len(n.split()) > 3)


def authors_match(cited: list[str], candidate: list[str],
                  record_complete: bool = True) -> bool:
    """Do the cited authors and the record's agree?

    Greedy one-to-one assignment has to pair up *every* cited name that reads as a person. A
    citation may name fewer authors than the record -- that is what "et al." means, and it is the
    one direction the rule is lenient in. Demanding two matched names instead of one refuses 22
    corpus references, every one of them a real work cited as "First Author et al.", and refuses
    no corruption that one matched name lets through.

    The other direction is the whole point. A cited name that no author of the record accounts for
    is either a fabrication or a citation error, and the fabrication it is looking for -- an
    invented author constellation spliced onto a real paper, with title, venue and pages all
    correct -- is invisible any other way. Measured over 250 real DBLP records, appending one
    invented name to the true author list used to be confirmed 250 times out of 250, because the
    bar was min(cited, stored) and padding raises only the cited side.

    Requiring every cited name to land costs recall where a record spells a name differently
    ("Rick Schlichting" for "Richard D. Schlichting"), and those references go to triage instead.
    That is the direction to be wrong in: a missed confirmation costs a human one lookup, and a
    false confirmation hides exactly what the tool exists to find.

    `record_complete` is the tier `VERIFICATION-SPEC.md` requires and it is decided from the data,
    never from a backend's name -- `record_authors_complete` for the record in hand,
    `mirror_authors_complete` for the run. Against a record that is *not* a complete list of the
    work's authors, an unmatched cited name is the record's gap rather than the citation's, and
    holding the citation to it is what turned 42 correctly cited corpus references into
    accusations. A name the record *contradicts* still refutes, whatever the record's state.

    An incomplete record is still a partial list, and the people it does list are evidence: a
    citation that pairs with none of them has had every name it offered come back foreign. DBLP
    keeps the first authors when it truncates and a citation names them first, so a correct
    citation of a truncated record pairs at least one. Without that bar the tier was a wildcard:
    "StarCoder 2" cited under two invented names verified against its 57-person record, and
    "Book Reviews", a title 922 records share, verified any author list at all through the one
    record that carries an `et al.` row. A record that lists no person -- a collaboration byline,
    `OpenAI` -- has nothing to pair against and still clears on the title, which is the limit of
    what this backend can say about such a work."""
    matched, comparable = matched_authors(cited, candidate)
    if not comparable:
        return False
    if matched + _split_person(cited, candidate) >= comparable:
        return True
    if record_complete or _contradicted(cited, candidate):
        return False
    return matched >= 1 or not _lists_people(candidate)


def _lists_people(candidate: list[str]) -> bool:
    """Does this byline name any person, as opposed to a group or a truncation mark alone?"""
    return any(len(_HOMONYM_SUFFIX.sub("", (a or "").strip()).split()) >= 2
               and not _CORPORATE.search(a or "") and not _ET_AL_ROW.match((a or "").strip())
               for a in candidate)


def _split_person(cited: list[str], candidate: list[str]) -> int:
    """How many cited entries are a second half of a person another entry already accounts for.

    `Zeller, Andreas. 2009. Why Programs Fail.` is one author, and a comma-delimited byline of two
    bare words cannot be told from a surname-only list of two people by looking at it -- so the
    parser leaves both readings on the table and the record settles it. Pairing is one-to-one, so
    "Zeller" and "Andreas" compete for the single record author "Andreas Zeller" and one of them is
    left over, which the rule above then reads as a person the record does not have.

    Safe because all three conditions have to hold at once: the entries pair with exactly one
    record author, with the *same* one, and their words together are contained in that author's
    name. An invented "Mallory Fake" pairs with nobody, so it is never excused; a citation that
    genuinely names two surnames pairs them with two different authors."""
    people = [n for n in cited if _is_person(n)]
    partners = {n: [a for a in candidate if _author_matches(n, a)] for n in people}
    excused = 0
    for author in candidate:
        group = [n for n in people if partners[n] == [author]]
        if len(group) < 2:
            continue
        words: set[str] = set()
        for n in group:
            words |= _name_parts(n)[0]
        if words and words <= _name_parts(author)[0]:
            excused += len(group) - 1
    return excused


def _contradicted(cited: list[str], candidate: list[str]) -> bool:
    """Does the record disagree with a cited name, rather than simply not carry it?

    The distinction is what makes leniency safe on an incomplete record. A record that lists
    "Jane Doe" and is cited for "John Doe" knows that surname and has a different person under it;
    a record that has never heard of "Thomas Wolf" says nothing about him at all. Only the first is
    evidence against the citation."""
    known: set[str] = set()
    for author in candidate:
        for words, _ in _name_readings(author):
            known |= words
    for name in cited:
        if not _is_person(name):
            continue
        if any(_author_matches(name, author) for author in candidate):
            continue
        words, _ = _name_parts(name)
        if words & known:
            return True
    return False


# A byline word that names a group rather than a person. Deliberately short: every word on it is
# one an invented author could hide behind, and "AI" is left off because it is also a given name
# ("Ai Chen") -- the one-word test below is what catches "OpenAI" and "DeepSeek-AI".
_CORPORATE = re.compile(r"\b(?:teams?|labs?|group|consortium|collaboration|inc|ltd|foundation"
                        r"|project)\b", re.I)
# What DBLP writes where it cut a long author list short. 191 publications in the mirror carry it.
_ET_AL_ROW = re.compile(r"^et\.?\s*al\.?$", re.I)


def record_authors_complete(candidate: list[str]) -> bool:
    """Does this record's byline read as the work's whole author list?

    Two ways it does not, and both are the database telling us so rather than a guess. DBLP writes
    a literal `et al.` row where it truncated the list -- the StarCoder 2 record stores 57 authors
    and the paper has 66. And a collaboration byline names the group, not the people: `OpenAI`,
    `Qwen Team`, `Llama Team`, `DeepSeek-AI` are how the mirror records the LLM technical reports
    an SE bibliography now cites constantly, and holding a correct citation of one against a
    single corporate name refuses 18 corpus references on the offline path."""
    if not candidate:
        return False
    if any(_ET_AL_ROW.match((a or "").strip()) for a in candidate):
        return False
    return any(len(_HOMONYM_SUFFIX.sub("", (a or "").strip()).split()) >= 2
               and not _CORPORATE.search(a or "") for a in candidate)


def mirror_authors_complete(db_path: str) -> bool:
    """Did this mirror's ingest keep the authors whose names carry a diacritic?

    An ingest that mangles the dump's character entities drops those authors from every publication
    they wrote, and the counts and titles all still look right. Against such a mirror the strict
    rule above is unsound in one direction: it reports an absence for references that are cited
    correctly -- 154 of the 2065-reference corpus, every one of them a real citation of a real
    paper. So the run decides which tier it is in, from the file in hand, exactly as
    `VERIFICATION-SPEC.md` requires; a repaired mirror gets the strict rule back with no code
    change.

    Answered once per file rather than once per reference: `second_opinion` asks for every
    reference in a run, and a fresh scan each time costs four minutes over a corpus."""
    try:
        st = os.stat(db_path)
    except OSError:
        return False
    return _mirror_authors_complete(db_path, st.st_mtime_ns, st.st_size)


# How far to read before concluding the ingest dropped them. A healthy mirror hits an accented name
# in the first few hundred rows; the bound is for the pathological case, and the scan stops at the
# first one it finds.
_ACCENTED_SCAN = 200000
# Below this the file is a fixture or a partial build and says nothing about entity handling, so it
# is treated as complete -- the safe direction, because that is the strict rule.
_MIRROR_MIN_AUTHORS = 1000


@functools.lru_cache(maxsize=8)
def _mirror_authors_complete(db_path: str, mtime_ns: int, size: int) -> bool:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        seen = 0
        for (name,) in con.execute("SELECT name FROM authors LIMIT ?", (_ACCENTED_SCAN,)):
            seen += 1
            if any(ord(c) > 127 for c in name or ""):
                return True
        return seen < _MIRROR_MIN_AUTHORS
    except sqlite3.Error:
        return False
    finally:
        con.close()


def absent_authors(cited: list[str], candidate: list[str]) -> list[str]:
    """The cited people no author of the record accounts for, in the citation's order.

    What a `mismatch` is made of, by name. `authors_match` refuses the citation and reports a
    count; this is the list a triager reads, and it is read off the same pairing: a name is absent
    when `_author_matches` pairs it with none of the record's authors, so a middle initial the
    record lacks, a particle on one side, a diacritic or a homonym suffix never put a real author
    here. Evidence for a human, never a verdict -- a name in the list is either a person the work
    does not have or a form of one it does that the pairing cannot read ("Rick" for "Richard
    D."), and the triage rules say the publication itself settles which. A citation that names
    the same person twice against a record that lists them once is refused by the one-to-one
    pairing and has no name here to show for it."""
    return [n for n in cited if _is_person(n)
            and _fold(n).replace(".", "").strip() not in ("et al", "others")
            and not any(_author_matches(n, a) for a in candidate)]


def matched_authors(cited: list[str], candidate: list[str]) -> tuple[int, int]:
    """(pairs formed, cited names that could be compared at all).

    Also how close a near miss was, which is what a reference reaching triage is shown: of several
    records sharing a title, the one that accounts for most of the cited authors is the one whose
    disagreement with the citation is worth reading."""
    cited = [a for a in cited if _is_person(a)
             and _fold(a).replace(".", "").strip() not in ("et al", "others")]
    if not cited or not candidate:
        return 0, 0
    return _max_matching(cited, list(candidate), _author_matches), len(cited)


def _max_matching(left: list, right: list, pairs) -> int:
    """How many of `left` can be paired with distinct members of `right`.

    Taking each in turn and keeping the first partner it fits is not enough: "Xin Xia" pairs with
    "Xin Xia 0001" and with "Xin Xiao", and if it takes the wrong one the citation's other author
    is left without a partner and a correctly cited paper is refused. Augmenting paths give the
    largest pairing whatever order the names come in."""
    partner: dict[int, int] = {}

    def augment(i: int, seen: set[int]) -> bool:
        for j, r in enumerate(right):
            if j in seen or not pairs(left[i], r):
                continue
            seen.add(j)
            if j not in partner or augment(partner[j], seen):
                partner[j] = i
                return True
        return False

    return sum(augment(i, set()) for i in range(len(left)))

def _index_fold(s: str) -> str:
    """A title as FTS5 tokenised it: diacritics stripped, but a letter carrying a stroke or a bar
    left alone.

    `unicode61` removes combining marks, so "Przybylek" finds "Przybyłek" in a *title* only if the
    query keeps the l-stroke -- folding it to a plain l, as an author comparison must, produces a
    token the index does not hold. 4,410 titles carry one of these letters and 98.7% of them could
    not find themselves."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _phrase_queries(title: str) -> list[str]:
    """FTS5 phrase queries for the title, in both hyphen readings and both letter foldings. A soft
    line-break hyphen ('Experimen-tation') must query as one token, a real compound
    ('Model-Driven') as two -- the wrong reading simply returns no rows, so both are asked."""
    queries = []
    for fold in (_fold, _index_fold):
        for variant in (title.replace("-", ""), title.replace("-", " ")):
            tokens = re.findall(r"[a-z0-9]+", fold(variant))
            if len(tokens) >= _MIN_TOKENS:
                q = '"' + " ".join(tokens) + '"'
                if q not in queries:
                    queries.append(q)
    return queries


def _and_query(title: str) -> list[str]:
    """An FTS5 AND query over the title's words, or [] if too few are selective enough.

    A hyphenated word contributes both of its readings as an OR -- `("nonuniform" OR ("non" AND
    "uniform"))` -- which is what a phrase query cannot do, since a phrase has to commit to one
    reading for the whole title. "Sample-based non-uniform random variate gener-ation" needs the
    compound reading for two of its words and the line-break reading for the third, and matches no
    phrase query at all."""
    groups = _and_groups(title)
    if len(groups) < _MIN_TOKENS:
        return []
    return [" AND ".join(groups[:10])]


# A word a two-column layout split with nothing to mark it -- "distributed sy stems", "pa ges".
# There is no hyphen to try both readings of, so the fragment goes into the AND query as a token
# the index does not hold and the whole title retrieves nothing. `titles_match` compares on letters
# alone and never saw the space, so the record was there to be found all along; this is retrieval
# catching up with the decision.
_SPLIT_WORD = 3


def _glued_query(title: str) -> list[str]:
    """AND queries with one short fragment glued to its neighbour, or [].

    One query per fragment rather than one query with every short word glued: a title's real short
    words ("a", "of", "in") are short too, and gluing them all at once asks for "astudy" and
    "ofsynthetic" and finds nothing. Which token is the fragment is not decidable here, so each is
    tried in turn, in both directions -- the break falls as often after the fragment ("sy stems")
    as before it. Asked last and only where the others found nothing, so the wrong guesses cost a
    query that matches nothing; the strict title comparison is still what decides."""
    words = [w for w in re.sub(r"[^a-z0-9 ]", " ", _fold(title)).split() if w]
    plain = [w for w in words if len(w) >= 4]
    out: list[str] = []
    for i, word in enumerate(words):
        if len(word) > _SPLIT_WORD:
            continue
        for j in (i + 1, i - 1):
            if not 0 <= j < len(words):
                continue
            merged = word + words[j] if j > i else words[j] + word
            terms = [merged] + [w for k, w in enumerate(words)
                                if k not in (i, j) and len(w) >= 4]
            if len(terms) < _MIN_TOKENS or sorted(terms) == sorted(plain):
                continue
            q = " AND ".join(f'"{t}"' for t in terms[:10])
            if q not in out:
                out.append(q)
        if len(out) >= 8:                             # a bounded last resort, not a sweep
            break
    return out


def _and_groups(title: str) -> list[str]:
    """The word groups `_and_query` joins, one per title word that is selective enough."""
    groups = []
    for word in _fold(title).split():
        parts = [t for t in re.findall(r"[a-z0-9]+", word) if t]
        if len(parts) == 1:
            if len(parts[0]) >= 4:
                groups.append(f'"{parts[0]}"')
        elif parts:
            joined = "".join(parts)
            split = " AND ".join(f'"{t}"' for t in parts)
            groups.append(f'("{joined}" OR ({split}))')
    return groups


# How many of the leave-a-pair-out queries to ask. A title has about ten selective words, so this
# is rarely reached; it bounds an entry that was never a title.
_MAX_DROPPED = 12


def _dropped_pair_queries(title: str) -> list[str]:
    """AND queries over the title's words with one adjacent pair left out, or [].

    A word split with nothing to mark it defeats every query that asks for it, on whichever side
    the split fell: a record whose title reads "Code Clone Detection U sing Functionally
    Equivalent Methods" holds no token "using", and a citation reading "tools, and chal lenges"
    asks for two tokens no record holds -- and `_glued_query` glues only a fragment of three
    letters or fewer, which "chal" is not. So is an article the layout glued to its neighbour
    ("Ac/c++ code vulnerability dataset"). Leaving out one adjacent pair covers all three: the
    remaining words are still most of the title, and `titles_match` compares on letters alone, so
    the split never reached the decision -- only retrieval. Asked last and only where nothing else
    matched, so a wrong guess costs a query that matches nothing."""
    groups = _and_groups(title)
    out: list[str] = []
    for i in range(len(groups)):
        rest = groups[:i] + groups[i + 2:]
        if len(rest) < max(_MIN_TOKENS, 3):
            continue
        q = " AND ".join(rest[:10])
        if q not in out:
            out.append(q)
        if len(out) >= _MAX_DROPPED:
            break
    return out


# A four-digit year as a citation prints it, and not the year-shaped segment of an IEEE DOI
# (`ICSE.2017.42`, `TSE.1975.6312836`) or of an arXiv identifier (`2005.14165`).
_CITED_YEAR = re.compile(r"(?<![\d/.])(?:19|20)\d{2}(?!\d|\.\d)")


def cited_years(text: str) -> set[str]:
    """Every year the citation prints, as strings.

    No parser here reads a year, and none has to: for choosing among records that already match
    the cited title and authors, every four-digit year in the entry is one the citation vouches
    for, and a page number or a volume that happens to look like a year costs nothing worse than
    the row order it replaces."""
    return set(_CITED_YEAR.findall(text or ""))


def queryable(title: str) -> bool:
    """Can this title be asked about at all? A title of one or two distinctive tokens is too
    generic for a phrase query to mean anything, and there is nothing to ask about an empty one."""
    return bool(_phrase_queries(title) or _and_query(title) or _glued_query(title))


def title_candidates(db_path: str, title: str, years=()) -> list[SecondOpinion]:
    """Every DBLP record whose title equals `title` after normalisation, the one to show first.

    Retrieval is generous -- three FTS queries, two hyphen readings plus a word-wise AND -- and the
    decision is the strict normalised equality applied to each row, so a wider net costs precision
    nothing. It earns its place on titles that need both hyphen readings at once: "Bi- Fuzz: A
    Two-Stage Fuzzing Tool for Open-World Video Games" matches neither the joined spelling
    ("twostage" is no token) nor the split one ("bi fuzz" is not the word).

    The list matters as a list: `Experimentation in Software Engineering` is three book editions, a
    1986 TSE article, a 1997 survey and a 2008 conference paper, and comparing the citation against
    whichever ranks first is how a real work gets reported missing. Its order matters too, because
    the first record that matches is the one `paper_url` points at: a published record before its
    preprint, and among those the record whose year is in `years`, the years the citation prints
    (`cited_years`)."""
    if not (title or "").strip():
        return []
    years = set(years or ())
    queries = _phrase_queries(title) + _and_query(title)
    if not (queries or _glued_query(title)):
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    out: list[SecondOpinion] = []
    try:
        seen: set[int] = set()
        extra = _extra_columns(con)
        cols = "".join(f", p.{c}" for c in extra)
        # The fragment-gluing and pair-dropping queries are a fallback and are asked only when
        # nothing else found the title: there are up to twenty of them, most of them guesses, and
        # asking them for every reference would multiply the query count of the backend that
        # decides nine confirmations in ten.
        for q in queries:
            try:
                rows = con.execute(
                    f"SELECT p.id, p.key, p.title{cols} FROM publications_fts f "
                    "JOIN publications p ON p.id = f.rowid "
                    "WHERE publications_fts MATCH ? LIMIT ?", (q, _MAX_CANDIDATES)).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                pid, key, cand_title = row[0], row[1], row[2]
                if pid in seen or not titles_match(title, cand_title):
                    continue
                seen.add(pid)
                cand_authors = [r[0] for r in con.execute(
                    "SELECT a.name FROM publication_authors pa "
                    "JOIN authors a ON a.id = pa.author_id WHERE pa.pub_id = ?", (pid,))]
                meta = dict(zip(extra, row[3:]))
                out.append(SecondOpinion(key=key, title=cand_title, authors=cand_authors,
                                         year=meta.get("year"), venue=meta.get("venue"),
                                         ee=meta.get("ee"), kind=meta.get("kind")))
        if not out:
            for q in _glued_query(title) + _dropped_pair_queries(title):
                try:
                    rows = con.execute(
                        f"SELECT p.id, p.key, p.title{cols} FROM publications_fts f "
                        "JOIN publications p ON p.id = f.rowid "
                        "WHERE publications_fts MATCH ? LIMIT ?", (q, _MAX_CANDIDATES)).fetchall()
                except sqlite3.Error:
                    continue
                for row in rows:
                    pid, key, cand_title = row[0], row[1], row[2]
                    if pid in seen or not titles_match(title, cand_title):
                        continue
                    seen.add(pid)
                    cand_authors = [r[0] for r in con.execute(
                        "SELECT a.name FROM publication_authors pa "
                        "JOIN authors a ON a.id = pa.author_id WHERE pa.pub_id = ?", (pid,))]
                    meta = dict(zip(extra, row[3:]))
                    out.append(SecondOpinion(key=key, title=cand_title, authors=cand_authors,
                                             year=meta.get("year"), venue=meta.get("venue"),
                                             ee=meta.get("ee"), kind=meta.get("kind")))
    finally:
        con.close()
    # 17% of corpus references carry a title two DBLP records share, almost always a CoRR preprint
    # beside the published version. Row order is arbitrary, so the published record is put first:
    # it is the one a triager needs to see, and it is what `paper_url` will point at. Among records
    # of the same standing the year the citation prints decides: Fowler's "Refactoring" is a 1999
    # book and a 2002 talk, Wohlin's "Experimentation in Software Engineering" three editions, and
    # a journal article often shares its title with the conference paper it grew from. Measured
    # over the 55-paper corpus, 48 verified references share their title with another published
    # record, and for 21 of them row order showed a record whose year the citation does not print
    # while another carried it; the year names the right one in all 21. The published record stays
    # ahead of the preprint whatever the years say -- a citation of the arXiv version prints the
    # preprint's year, and 51 references would otherwise have landed on it.
    out.sort(key=lambda c: ((c.venue or "").strip().lower() == "corr", str(c.year) not in years))
    return out


def second_opinion(db_path: str, title: str, authors: list[str]) -> SecondOpinion | None:
    """The DBLP record confirming (title, authors), or None. Strict by design: an exact
    normalized-title equality plus a full author match on some same-title candidate.

    The author rule runs at the tier the data supports -- this mirror's ingest, and each record's
    own byline -- so a record DBLP truncated or credited to a collaboration cannot be read as an
    absence."""
    if not authors:
        return None
    complete_mirror = mirror_authors_complete(db_path)
    return next((c for c in title_candidates(db_path, title)
                 if authors_match(authors, c.authors,
                                  complete_mirror and record_authors_complete(c.authors))), None)


def record_context(db_path: str, title: str) -> dict | None:
    """DBLP's own metadata for a uniquely title-matching record, as evidence for a human.

    Deliberately not a check. Measured over the corpus, comparing these fields automatically is far
    too noisy to demote a reference on: DBLP's venue strings are abbreviations that legitimately do
    not appear in a citation ("CoRR", "ESEC/SIGSOFT FSE" -- 27% disagreed), a work often has two
    valid DOIs (preprint and published, ACM Queue and CACM, IEEE's own duplicates -- 6.7% still
    disagreed after excluding truncations and arXiv), and no parser here reads a year, so a year
    check mostly measures whichever four-digit number a regex found in the raw citation. Shown to
    the triager, who can tell a wrong year from an online-first one, the same fields are useful.

    No author check here: this is context for a reference already going to review, not a
    confirmation. Returns None unless exactly one record carries the title."""
    if not (title or "").strip():
        return None
    # `_phrase_queries` asks both hyphen readings of the whole title, which fails when one title
    # needs both at once: "Refactoring ... de-velopers keep up-to-date" matches neither the joined
    # spelling ("uptodate" is no token) nor the split one ("de velopers" is not the word). Falling
    # back to an AND over the words that carry no hyphen at all sidesteps the question -- the
    # remaining words are more than selective enough, and the loose title comparison below is what
    # actually decides.
    queries = _phrase_queries(title) + _and_query(title)
    if not queries:
        return None
    # Compare with every non-alphanumeric removed on both sides -- `_letters`, the same reduction
    # the confirmation path uses. A title broken across a line keeps its hyphen ("de-velopers"),
    # and a real one may carry its own ("Up-to-Date"); dropping them everywhere makes both agree
    # without having to know which is which. What it does *not* carry is `titles_match`'s tolerance
    # for a subtitle on one side only: this has to name exactly one record to be evidence at all,
    # and that tolerance is what would make two of them.
    want = _letters(title)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        extra = _extra_columns(con)
        if not extra:
            return None
        cols = "".join(f", p.{c}" for c in extra)
        hits: dict[int, dict] = {}
        for q in queries:
            try:
                rows = con.execute(
                    f"SELECT p.id, p.key, p.title{cols} FROM publications_fts f "
                    "JOIN publications p ON p.id = f.rowid "
                    "WHERE publications_fts MATCH ? LIMIT ?", (q, _MAX_CANDIDATES)).fetchall()
            except sqlite3.Error:
                continue
            for row in rows:
                if _letters(row[2]) == want:
                    hits[row[0]] = {"key": row[1], **dict(zip(extra, row[3:]))}
        if len(hits) != 1:
            return None
        return next(iter(hits.values()))
    finally:
        con.close()


# How far a title may be from the cited one, in word-level edits, and still be offered as the
# mirror's nearest: a dropped "and", one content word changed, a subtitle word added -- the shapes
# the corpus residue takes ("An in-depth study" for "An In-depth Empirical Study", "state-aware"
# for "Context-Aware"). At three a title is a different title.
_NEAREST_EDITS = 2
# The leave-out queries are asked over at most this many of the title's selective words, so a long
# title costs at most 45 queries.
_NEAREST_WORDS = 10
# How many near titles are read for the author gate. Past this a title is generic enough that a
# near miss says little, and each candidate costs an author lookup.
_NEAREST_CANDIDATES = 100


def _title_words(title: str) -> list[str]:
    """A title as the word sequence the edit distance runs over: folded, hyphens closed,
    punctuation gone -- the reduction `_letters` makes, kept as words."""
    return re.findall(r"[a-z0-9]+", _fold((title or "").replace("-", "")))


def _word_edits(a: list[str], b: list[str]) -> int:
    """Levenshtein distance over two word sequences. A title is a dozen words, so the plain table
    is cheaper than anything cleverer."""
    prev = list(range(len(b) + 1))
    for i, wa in enumerate(a, 1):
        cur = [i]
        for j, wb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wa != wb)))
        prev = cur
    return prev[-1]


def _nearest_queries(title: str) -> list[str]:
    """AND queries over the title's selective words with two of them left out, or one where the
    title is too short for two, or [].

    A record within two word edits of the cited title still carries all but two of its words, so
    leaving every pair out retrieves it whichever two moved. Where leaving two out would leave
    fewer than three, one is left out and the offer reaches one edit; a title with fewer than
    four selective words is not asked about at all, which is also where `queryable` stops."""
    groups = _and_groups(title)[:_NEAREST_WORDS]
    n = len(groups)
    out: list[str] = []
    if n - 2 >= 3:
        for i in range(n):
            for j in range(i + 1, n):
                out.append(" AND ".join(g for k, g in enumerate(groups) if k not in (i, j)))
    elif n - 1 >= 3:
        for i in range(n):
            out.append(" AND ".join(g for k, g in enumerate(groups) if k != i))
    return out


def _nearest_candidates(db_path: str, title: str) -> list[dict]:
    """Every record within `_NEAREST_EDITS` word edits of the cited title, nearest first, each with
    its authors and metadata. Ungated: `nearest_title` is what applies the author gate, and this
    is separate so the gate's effect can be measured."""
    want = _title_words(title)
    queries = _nearest_queries(title)
    if not want or not queries:
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        extra = _extra_columns(con)
        cols = "".join(f", p.{c}" for c in extra)
        near: dict[int, tuple[int, str, str]] = {}
        wanted = set(want)
        for q in queries:
            try:
                rows = con.execute(
                    f"SELECT p.id, p.key, p.title FROM publications_fts f "
                    "JOIN publications p ON p.id = f.rowid "
                    "WHERE publications_fts MATCH ? LIMIT ?", (q, _MAX_CANDIDATES)).fetchall()
            except sqlite3.Error:
                continue
            for pid, key, cand_title in rows:
                if pid in near:
                    continue
                words = _title_words(cand_title)
                # Two cheap necessary conditions before the table: an edit moves one word, so
                # the lengths and the shared words are both within the bound.
                if (abs(len(words) - len(want)) > _NEAREST_EDITS
                        or len(wanted & set(words)) < len(wanted) - _NEAREST_EDITS):
                    continue
                edits = _word_edits(want, words)
                if edits <= _NEAREST_EDITS:
                    near[pid] = (edits, key, cand_title)
        out: list[dict] = []
        for pid, (edits, key, cand_title) in sorted(near.items(), key=lambda kv: kv[1][0])[
                :_NEAREST_CANDIDATES]:
            authors = [r[0] for r in con.execute(
                "SELECT a.name FROM publication_authors pa "
                "JOIN authors a ON a.id = pa.author_id WHERE pa.pub_id = ?", (pid,))]
            meta = {}
            if extra:
                row = con.execute(f"SELECT p.id{cols} FROM publications p WHERE p.id = ?",
                                  (pid,)).fetchone()
                meta = dict(zip(extra, row[1:])) if row else {}
            out.append({"key": key, "title": cand_title, "authors": authors, "edits": edits,
                        **{k: v for k, v in meta.items() if v not in (None, "")}})
    finally:
        con.close()
    # Nearest first; of two records at the same distance the published one before its preprint,
    # as `title_candidates` orders them.
    out.sort(key=lambda c: (c["edits"], (c.get("venue") or "").strip().lower() == "corr"))
    return out


def nearest_title(db_path: str, title: str, authors: list[str]) -> dict | None:
    """The mirror's nearest title, offered only when every cited person is on that record.

    A sibling of `record_context` for the residue where no record carries the cited title. It
    runs on a citation the DBLP backend answered `no_match` for, offers a record whose title is
    within `_NEAREST_EDITS` word-level edits of the cited one, and requires every cited person to
    be an author of it. The gate is what makes it evidence rather than noise: the same authors on a
    title one word off is how a slipped content word ("in-depth study" for "In-depth Empirical
    Study") looks, while a near title under other people is a different work, and offering it
    would argue a correct citation of an uncovered work into a "citation error".

    Evidence for a human, never a confirmation: the triage rules say a person confirms a title
    that differs in a content word, and nothing here changes a status."""
    if not (title or "").strip() or not authors:
        return None
    for candidate in _nearest_candidates(db_path, title):
        if authors_match(list(authors), candidate["authors"], record_complete=True):
            return candidate
    return None
