"""Second-opinion check against the offline DBLP database.

hallucinator's offline DBLP backend matches a reference against a single FTS candidate, so a
cited title that several publications share is compared with whichever candidate ranks first --
"Experimentation in Software Engineering" hits Basili's 1986 TSE article, the author check fails,
and Wohlin's identically-titled book reports `not_found` even though the database holds it. This
module re-asks the same SQLite file the question hallucinator was asked, but over *all*
same-title candidates: an exact normalized-title match plus an initials-aware author match on any
candidate confirms the reference.

This check can only clear a reference, never flag one, and it is deliberately strict:

* The cited title must equal the candidate's title after normalization (case, punctuation,
  hyphens, whitespace) -- never a similarity score.
* Every *comparable* author must match: greedy one-to-one assignment has to pair up
  min(cited, stored) authors, at least two of them (unless both sides list exactly one).
  The offline database itself stores truncated author lists (the Wohlin/Runeson book carries
  3 of its 6 authors; MeyerFMZ14 lacks Meyer), so demanding that every cited author match
  would refute real references for the database's omissions -- while a citation that pads or
  swaps authors still fails, because the stored authors it contradicts stay unmatched.

Written from the database schema alone (4 tables + an FTS5 index, the same file
`hallucinator-cli update-dblp` builds); no hallucinator code involved.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

# Titles with fewer FTS tokens than this are too generic for a phrase query to be meaningful
# ("Design Rules" would sweep in every same-phrase record); leave those to triage.
_MIN_TOKENS = 3
_MAX_CANDIDATES = 50


@dataclass
class SecondOpinion:
    key: str                 # DBLP record key, e.g. "books/daglib/0029933"
    title: str               # the candidate's title as stored
    authors: list[str]       # the candidate's full author list


def _fold(s: str) -> str:
    """Lowercase and strip diacritics, so 'Höst'/'Wesslén' compare against their ASCII forms."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _norm_title(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", _fold(t or "").replace("-", ""))).strip()


def _name_parts(name: str) -> tuple[set[str], set[str]]:
    """(name words, initials) of one author string, in any of the conventions bibliographies use:
    'Claes Wohlin', 'Wohlin C', 'Wohlin, C.', 'de Dieu MJ', 'V. Richard Benjamins'. A token of
    1-4 capitals is an initials run ('MJ' -> m, j); anything longer is a name word."""
    words: set[str] = set()
    initials: set[str] = set()
    for tok in re.split(r"[\s.,]+", name):
        if not tok or tok.isdigit() or _fold(tok) in ("et", "al", "others"):
            continue  # digits: DBLP homonym suffixes ("Thomas Zimmermann 0001")
        if (len(tok) <= 4 and tok.isalpha() and tok[0].isupper()
                and sum(c.isupper() for c in tok) >= min(2, len(tok))):
            # An initials run: "MJ", "C", also mixed-case with a particle letter ("CEdC" for
            # "Carlos Eduardo de Carvalho"). Only the capitals are initials.
            initials.update(_fold(c) for c in tok if c.isupper())
        elif len(tok) == 1:
            initials.add(_fold(tok))
        else:
            words.update(_fold(w) for w in tok.split("-") if w)
    return words, initials


def _author_matches(cited: str, candidate: str) -> bool:
    """Does the cited author name plausibly denote the candidate author? Every cited name word
    must appear in the candidate's words, and every cited initial must begin one of them."""
    cw, ci = _name_parts(cited)
    dw, di = _name_parts(candidate)
    if not cw or not cw <= dw:
        return False
    starts = {w[0] for w in dw} | di
    return ci <= starts


def _authors_match(cited: list[str], candidate: list[str]) -> bool:
    """Do the author lists agree as far as they can be compared? Greedy one-to-one assignment
    must pair up min(len(cited), len(candidate)) authors -- both lists can be truncations (an
    'et al.' citation, or the offline database's own incomplete author rows), so the shorter
    side sets the bar -- and at least two pairs must match unless both sides list exactly one
    author. An unmatched author on the *shorter* side refutes: it names someone the other list
    contradicts rather than omits."""
    cited = [a for a in cited if a and _fold(a).replace(".", "").strip() not in ("et al", "others")]
    if not cited or not candidate:
        return False
    remaining = list(candidate)
    matched = 0
    for a in cited:
        hit = next((d for d in remaining if _author_matches(a, d)), None)
        if hit is not None:
            remaining.remove(hit)
            matched += 1
    need = min(len(cited), len(candidate))
    return matched >= need and (matched >= 2 or (len(cited) == len(candidate) == 1))


def _phrase_queries(title: str) -> list[str]:
    """FTS5 phrase queries for the title, in both hyphen readings. A soft line-break hyphen
    ('Experimen-tation') must query as one token, a real compound ('Model-Driven') as two --
    the wrong reading simply returns no rows, so both are asked."""
    queries = []
    for variant in (title.replace("-", ""), title.replace("-", " ")):
        tokens = re.findall(r"[a-z0-9]+", _fold(variant))
        if len(tokens) >= _MIN_TOKENS:
            q = '"' + " ".join(tokens) + '"'
            if q not in queries:
                queries.append(q)
    return queries


def second_opinion(db_path: str, title: str, authors: list[str]) -> SecondOpinion | None:
    """The DBLP record confirming (title, authors), or None. Strict by design: an exact
    normalized-title equality plus a full author match on some same-title candidate."""
    if not (title or "").strip() or not authors:
        return None
    queries = _phrase_queries(title)
    if not queries:
        return None
    want = _norm_title(title)
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None
    try:
        seen: set[int] = set()
        for q in queries:
            try:
                rows = con.execute(
                    "SELECT p.id, p.key, p.title FROM publications_fts f "
                    "JOIN publications p ON p.id = f.rowid "
                    "WHERE publications_fts MATCH ? LIMIT ?", (q, _MAX_CANDIDATES)).fetchall()
            except sqlite3.Error:
                continue
            for pid, key, cand_title in rows:
                if pid in seen or _norm_title(cand_title) != want:
                    continue
                seen.add(pid)
                cand_authors = [r[0] for r in con.execute(
                    "SELECT a.name FROM publication_authors pa "
                    "JOIN authors a ON a.id = pa.author_id WHERE pa.pub_id = ?", (pid,))]
                if _authors_match(authors, cand_authors):
                    return SecondOpinion(key=key, title=cand_title, authors=cand_authors)
    finally:
        con.close()
    return None
