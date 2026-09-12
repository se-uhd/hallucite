"""Verify a batch of parsed references against bibliographic databases.

The second of the two operations `VERIFICATION-SPEC.md` describes: references in, one result each,
aligned to the input. Five backends answer, cheapest first, and each is asked only about the
references the ones before it did not already match -- so the network cost falls on the hard
residue, which is exactly the set a human will be asked to judge.

* `DBLP` -- the offline mirror, through `dblp_check`: a title and author match over *all* the
  records sharing the cited title.
* `CrossRef` -- its bibliographic search, then the same title and author match over the top hits.
* `DOI` -- `api.crossref.org/works/<doi>`, then doi.org content negotiation for every other
  registry: does the cited DOI resolve, and does it resolve to this work.
* `arXiv` -- `export.arxiv.org` by identifier, a hundred at a time: does the cited id exist, and
  does it name this work.
* `Semantic Scholar` -- its paper search, one reference at a time and only where a key is
  configured. It indexes technical reports and theses the others do not.

Two rules run through all of it. Nothing is decided on a similarity score: a backend confirms a
reference only when a record's title matches after normalisation *and* its authors match on an
initial-and-surname fingerprint, both of which `dblp_check` already implements and every backend
shares. And a backend that could not answer -- a timeout, a transport error, a rate limit
-- says so, and is never silently folded into "no match", because a `not_found` from an incomplete
run is a weaker claim than one from a complete run and triage is told to treat it as such.

What this does not cover: Open Library, PubMed and Europe PMC. Over the 41-paper corpus they decide
1.4% of confirmations between them -- the statistics classics an empirical paper cites, and the
books it cites without a DOI -- and a reference only they would have matched is reported here as
`not_found`, honestly a weaker search rather than a stronger claim. Retractions are reported only where CrossRef answered about
the reference anyway, since it carries them in the record it was going to return; a reference the
offline mirror confirms is never retraction-checked, because asking would cost a request per
confirmed reference.
"""

from __future__ import annotations

import gzip
import html
import json
import os
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from dblp_check import (authors_match, cited_years, matched_authors, mirror_authors_complete,
                        normalized_title, queryable, record_authors_complete, title_candidates,
                        titles_match)
from reference_parser import Reference, parse_reference  # noqa: F401  (re-exported: one module,
                                                         # both operations of the contract)

DEFAULT_DBLP = os.environ.get("HALLUCITE_DBLP") or str(Path.home() / "hallucite" / "dblp.db")

DBLP = "DBLP"
CROSSREF = "CrossRef"
DOI = "DOI"
ARXIV = "arXiv"
SEMANTIC_SCHOLAR = "Semantic Scholar"
BACKENDS = (DBLP, CROSSREF, DOI, ARXIV, SEMANTIC_SCHOLAR)

# Per-backend outcomes. `skipped` says the backend was not applicable or was not needed, never that
# it disagreed; the three failure values say it did not answer at all.
MATCH, NO_MATCH, AUTHOR_MISMATCH = "match", "no_match", "author_mismatch"
TIMEOUT, ERROR, RATE_LIMITED, SKIPPED = "timeout", "error", "rate_limited", "skipped"
DID_NOT_ANSWER = (TIMEOUT, ERROR, RATE_LIMITED)

# Per-reference outcomes.
VERIFIED, NOT_FOUND, MISMATCH = "verified", "not_found", "mismatch"

CROSSREF_WORKS = "https://api.crossref.org/works"
DOI_ORG = "https://doi.org/"
ARXIV_API = "http://export.arxiv.org/api/query"
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
_ATOM = "{http://www.w3.org/2005/Atom}"
# arXiv takes up to 100 ids per request; the pause between requests is what its
# export API asks for, and going without it is what earns a long block.
_ARXIV_BATCH = 100
_ARXIV_PAUSE = 3.0
# How many identifiers a batch omitted are asked for again on their own. Bounded
# because each costs a paced request, and an unbounded re-check of a long residue is
# what earns the block this pacing exists to avoid.
_ARXIV_RECHECK = 20
# Semantic Scholar answers one reference per request and rate-limits hard, so it is paced and it is
# asked last. Without a key it is not asked at all -- see `_semantic_scholar`.
_S2_PAUSE_KEYED = 1.1
# Its search is slow even when it is not throttling: single requests take several seconds, and the
# ordinary 15 s ceiling turns that into a timeout that claims nothing about the reference.
_S2_TIMEOUT = 45.0
# doi.org's content negotiation is slower still: it redirects to whichever registry holds the DOI,
# and a DataCite record took 8 to 32 seconds to come back. Measured over real Zenodo DOIs, the
# ordinary ceiling turned answers into timeouts on exactly the artifact and dataset references that
# have no other identifier to check.
_DOI_ORG_TIMEOUT = 45.0
# Consecutive refusals after which the backend stops asking. It has to survive a burst: Semantic
# Scholar throttles for a few seconds at a time even under a key, and a low threshold turns that
# into a backend that sits out the rest of the corpus. At three it did exactly that, and cost 27
# confirmations against the run before it. What the threshold is really for is a block that lasts,
# where asking on would mark every remaining reference degraded and tell triage that no negative in
# the whole run is clean.
_S2_GIVE_UP_AFTER = 25
# After this many refusals however they fall, stop paying for retries -- but keep asking. The
# consecutive counter above only trips on an unbroken run, and this backend throttles
# *intermittently*: one answer in twenty resets it, so on a real corpus it never trips and every
# refused reference pays the whole ladder below (2+4+8+16 s of backoff on top of a 45 s ceiling).
# That is what put a 2065-reference replay three hours in this one backend. Measured on the
# residue: a refusal costs 31 s with the ladder and about a second without it, while an answer
# takes 3 to 18 s either way. Capping the *asking* instead was tried and cost five confirmations no
# other backend reaches -- the ladder is the expense, not the question.
_S2_PATIENCE = 25
# Extra attempts for this backend alone, on top of the caller's. Each one doubles its wait.
_S2_RETRIES = 4


@dataclass
class DbResult:
    db_name: str
    status: str
    elapsed_ms: float = 0.0
    found_authors: list[str] = field(default_factory=list)
    paper_url: str | None = None


@dataclass
class DoiInfo:
    doi: str
    valid: bool
    title: str | None = None


@dataclass
class ArxivInfo:
    arxiv_id: str
    valid: bool
    title: str | None = None


@dataclass
class RetractionInfo:
    is_retracted: bool
    retraction_doi: str | None = None
    retraction_source: str | None = None


@dataclass
class ValidationResult:
    status: str
    source: str | None = None
    found_authors: list[str] = field(default_factory=list)
    paper_url: str | None = None
    doi_info: DoiInfo | None = None
    arxiv_info: ArxivInfo | None = None
    retraction_info: RetractionInfo | None = None
    failed_dbs: list[str] = field(default_factory=list)
    db_results: list[DbResult] = field(default_factory=list)

    def absorb(self, answer) -> None:
        """Take in one backend's answer. Evidence a backend gathered is kept even when a later one
        decides the verdict, since a dead DOI matters whoever confirms the title."""
        self.db_results.append(answer.db_result)
        self.doi_info = self.doi_info or answer.doi_info
        self.arxiv_info = self.arxiv_info or answer.arxiv_info
        self.retraction_info = self.retraction_info or answer.retraction


# ── HTTP ─────────────────────────────────────────────────────────────────────

_MAX_RETRY_WAIT = 30.0


def _fetch(url: str, accept: str, timeout: float, user_agent: str, retries: int,
           extra_headers: dict | None = None) -> tuple[bytes | None, str]:
    """(body, outcome), where outcome is `ok`, `not_found` or one of the did-not-answer values.

    A 404 is an answer -- the record is not there -- and has to stay distinct from a rate limit or
    a transport failure, which are not answers about the reference at all."""
    request = urllib.request.Request(
        url, headers={"Accept": accept, "User-Agent": user_agent, **(extra_headers or {})})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as fh:
                return _body(fh), "ok"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None, "not_found"
            if exc.code in (429, 503) and attempt < retries:
                time.sleep(min(_retry_after(exc, attempt), _MAX_RETRY_WAIT))
                continue
            return None, RATE_LIMITED if exc.code in (429, 503) else ERROR
        except socket.timeout:
            return None, TIMEOUT
        except urllib.error.URLError as exc:
            return None, TIMEOUT if isinstance(exc.reason, socket.timeout) else ERROR
        except Exception:                            # noqa: BLE001
            # Everything a connection can do to a client. `IncompleteRead` and `zlib.error` are
            # neither `OSError` nor `ValueError`, and one truncated response must not cost a paper
            # its verification -- the backend simply did not answer.
            return None, ERROR
    return None, ERROR


def _body(response) -> bytes:
    """The response body, decompressed if the server compressed it.

    Only when it says so: CrossRef gzips above a size threshold and not below it, so decompressing
    unconditionally fails on exactly the small responses."""
    raw = response.read()
    encoding = (response.headers or {}).get("Content-Encoding", "")
    if "gzip" in encoding.lower():
        try:
            return gzip.decompress(raw)
        except Exception:                            # noqa: BLE001 -- a body that lied about
            return raw                               # its encoding is still a body
    return raw


def _retry_after(exc: urllib.error.HTTPError, attempt: int) -> float:
    """How long to wait before trying again.

    Semantic Scholar throttles without naming a Retry-After, so a fixed pause just walks back into
    the same limit. Doubling per attempt rides it out, which is also what its API asks callers to
    do."""
    value = (exc.headers or {}).get("Retry-After", "")
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return min(2.0 * (2 ** attempt), _MAX_RETRY_WAIT)


def _fetch_json(url: str, timeout: float, user_agent: str, retries: int) -> tuple[dict | None, str]:
    body, outcome = _fetch(url, "application/json", timeout, user_agent, retries)
    if outcome != "ok":
        return None, outcome
    try:
        return json.loads(body), "ok"
    except (ValueError, UnicodeDecodeError):
        return None, ERROR      # a JSON endpoint answering with HTML has not answered


# ── record shapes ────────────────────────────────────────────────────────────

_MARKUP = re.compile(r"<[^>]{1,40}>")
# Publishers rewrite a retracted article's title in place. The citation names the work as it was
# published, so the marker has to come off before the titles are compared -- and it is itself
# evidence, since it is deposited even where the retraction relation is not.
_RETRACTED_TITLE = re.compile(
    r"^\s*(?:retracted(?:\s+article)?|withdrawn|expression\s+of\s+concern)\s*[:\-]\s*", re.I)


def _plain(text: str) -> str:
    """A title as CrossRef stores it, reduced to text.

    Its records carry markup -- `<i>`, `<scp>`, MathML, HTML entities -- and normalisation strips
    the angle brackets but keeps the tag name, so an unstripped `<i>N</i>` turns into the letters
    "i n i" and the title stops matching itself."""
    return " ".join(html.unescape(_MARKUP.sub("", text or "")).split())


@dataclass
class _Record:
    """One candidate publication, reduced to what a verdict needs."""
    title: str
    authors: list[str]
    url: str | None = None
    retraction: RetractionInfo | None = None


def _retraction(item: dict) -> RetractionInfo | None:
    """Whether CrossRef says this work has been retracted.

    Publishers deposit the relation in both directions and not consistently in either: the Lancet's
    retracted hydroxychloroquine paper carries its retractions under `update-to`, which by the
    field's own definition belongs on the notice. Both are therefore read, and so is the marker
    publishers write into the title. The claim this produces is "a human should look", not a
    verdict, so pointing at a retraction notice by mistake costs a check rather than an error."""
    for key in ("updated-by", "update-to"):
        for update in item.get(key) or []:
            if (update.get("type") or "").lower() == "retraction":
                return RetractionInfo(is_retracted=True, retraction_doi=update.get("DOI"),
                                      retraction_source=update.get("source") or "CrossRef")
    if any(_RETRACTED_TITLE.match(t) for t in (item.get("title") or []) if t):
        return RetractionInfo(is_retracted=True, retraction_source="CrossRef title")
    return None


def _crossref_record(item: dict) -> _Record:
    names = []
    for a in item.get("author") or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name") or ""
        if name.strip():
            names.append(name.strip())
    titles = [_plain(_RETRACTED_TITLE.sub("", t)) for t in (item.get("title") or []) if t]
    subtitles = [_plain(t) for t in (item.get("subtitle") or []) if t]
    title = titles[0] if titles else ""
    if subtitles and normalized_title(subtitles[0]) not in normalized_title(title):
        title = f"{title}: {subtitles[0]}"
    doi = item.get("DOI")
    return _Record(title=title, authors=names, url=f"{DOI_ORG}{doi}" if doi else None,
                   retraction=_retraction(item))


def _csl_record(item: dict) -> _Record:
    names = []
    for a in item.get("author") or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("literal") or ""
        if name.strip():
            names.append(name.strip())
    title = item.get("title")
    if isinstance(title, list):
        title = title[0] if title else ""
    title = _plain(_RETRACTED_TITLE.sub("", title or ""))
    doi = item.get("DOI") or item.get("doi")
    return _Record(title=title, authors=names, url=f"{DOI_ORG}{doi}" if doi else None)


def _query_forms(title: str) -> list[str]:
    """The title as a search engine should be asked for it.

    A line break inside a word survives into the title as a hyphen ("Modeling library popu-larity")
    and no search index holds that spelling, so the joined reading is asked as well. The offline
    mirror already tries both readings itself; the online searches were being sent the raw string
    and finding nothing."""
    forms = [title]
    joined = title.replace("-", "")
    if joined != title and joined.strip():
        forms.append(joined)
    return forms


def _s2_record(item: dict) -> _Record:
    names = [a.get("name", "").strip() for a in (item.get("authors") or []) if a.get("name")]
    doi = (item.get("externalIds") or {}).get("DOI")
    return _Record(title=_plain(item.get("title") or ""), authors=names,
                   url=item.get("url") or (f"{DOI_ORG}{doi}" if doi else None))


def _verdict(ref, record: _Record, complete_source: bool = True) -> str:
    """`match`, `author_mismatch` or `no_match` for one candidate record.

    Title first, and the two questions stay apart: a record whose title is the cited one but whose
    authors are not is evidence a human needs, and folding it into `no_match` throws away the one
    case where a citation names a real work and the wrong people.

    Where the authors cannot be compared at all -- the entry names none, the record stores none,
    or nothing the entry lists reads as a person's name -- the answer is `no_match`. Nothing was
    contradicted, but nothing was confirmed either, and a title alone is not a confirmation:
    `dblp_check` has always refused to clear on one, and letting a second backend do it would put
    the decision back where the mirror's own truncated author rows can reach it.

    `complete_source` is the run's half of the tier `VERIFICATION-SPEC.md` requires; the record's
    own half is read off the byline here. Both have to hold before an unmatched cited name counts
    as an absence."""
    # `titles_match` refuses a pair whose letters both reduce to nothing, which is what keeps two
    # titles in scripts this normalisation cannot read from matching each other.
    if not titles_match(getattr(ref, "title", "") or "", record.title):
        return NO_MATCH
    cited = [a for a in (getattr(ref, "authors", None) or []) if a]
    if not cited or not record.authors:
        return NO_MATCH
    # An "author list" of nothing but venue fragments the parser bled in is not a disagreement
    # about authorship; reporting `author_mismatch` would show a triager a near miss that was
    # never compared.
    if not matched_authors(cited, record.authors)[1]:
        return NO_MATCH
    complete = complete_source and record_authors_complete(record.authors)
    return MATCH if authors_match(cited, record.authors, complete) else AUTHOR_MISMATCH


def _best(ref, records: list[_Record], complete_source: bool = True
          ) -> tuple[str, _Record | None]:
    """The strongest verdict any candidate supports, and the record that supports it.

    Where nothing matches, the near miss reported is the record accounting for most of the cited
    authors. Several publications can share a title -- "Experimentation in Software Engineering" is
    a book, a 1986 TSE article and four other works -- and showing a triager whichever came back
    first is how a citation gets held against a paper it never claimed to be."""
    best, best_record, closest = NO_MATCH, None, -1
    for record in records:
        verdict = _verdict(ref, record, complete_source)
        if verdict == MATCH:
            return MATCH, record
        if verdict != AUTHOR_MISMATCH:
            continue
        matched, _ = matched_authors(list(getattr(ref, "authors", None) or []), record.authors)
        if matched > closest:
            best, best_record, closest = AUTHOR_MISMATCH, record, matched
    return best, best_record


@dataclass
class _Answer:
    """What one backend has to say about one reference: a verdict, plus whatever it learned on the
    way that a human reading the residue will want."""
    db_result: DbResult
    doi_info: DoiInfo | None = None
    arxiv_info: ArxivInfo | None = None
    retraction: RetractionInfo | None = None


def _dblp_readable(path: str) -> bool:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.execute("SELECT 1 FROM publications LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return False
    return True


def _backend_of(run) -> str:
    """The backend a bound method belongs to, for naming a failure it did not survive to report."""
    return {"_dblp": DBLP, "_crossref": CROSSREF, "_doi": DOI, "_arxiv": ARXIV,
            "_semantic_scholar": SEMANTIC_SCHOLAR}.get(getattr(run, "__name__", ""), "backend")


def _answer(db_name: str, ref, records: list[_Record], elapsed_ms: float,
            complete_source: bool = True, **evidence) -> _Answer:
    """One backend's answer, from the candidates it retrieved."""
    status, record = _best(ref, records, complete_source)
    if record is None:
        return _Answer(DbResult(db_name, status, elapsed_ms), **evidence)
    return _Answer(DbResult(db_name, status, elapsed_ms, list(record.authors), record.url),
                   retraction=record.retraction, **evidence)


# ── the verifier ─────────────────────────────────────────────────────────────

class Verifier:
    """Holds the configuration a batch is checked under. `check` may be called repeatedly."""

    def __init__(self, dblp_path: str | None = DEFAULT_DBLP, mailto: str = "",
                 timeout: float = 15.0, max_workers: int | None = None,
                 rate_limit_retries: int = 2, s2_api_key: str | None = None,
                 disabled_dbs: tuple[str, ...] | list[str] = ()) -> None:
        self.dblp_path = dblp_path if dblp_path and Path(dblp_path).exists() else None
        # A file that is not a readable mirror -- the bot-check page a failed download leaves
        # behind ingests as a valid, empty, useless database -- must report a failure, not a
        # confident "not there" for every reference in the run.
        self.dblp_readable = self.dblp_path is not None and _dblp_readable(self.dblp_path)
        # Which tier the mirror in hand puts DBLP in, decided once per run and never from the
        # backend's name (`VERIFICATION-SPEC.md`, "The phantom-author rule"). An ingest that
        # mangled the dump's character entities dropped every author whose name carries a
        # diacritic, and against that mirror an unmatched cited name is the record's gap, not the
        # citation's -- 154 of the 2065-reference corpus, all cited correctly.
        self.dblp_authors_complete = (self.dblp_readable
                                      and mirror_authors_complete(self.dblp_path))
        self.mailto = mailto
        self.timeout = timeout
        # CrossRef puts a caller who gives a contact address in its polite pool, which allows three
        # requests at a time; without one the limit is one, and exceeding it is what earns a 429.
        self.max_workers = max(1, max_workers if max_workers is not None else (3 if mailto else 1))
        self.rate_limit_retries = max(0, rate_limit_retries)
        self.s2_api_key = (s2_api_key if s2_api_key is not None
                           else os.environ.get("S2_API_KEY", ""))
        self.disabled = set(disabled_dbs)
        contact = f"; mailto:{mailto}" if mailto else ""
        self.user_agent = f"hallucite (reference verification{contact})"

    # -- backends -------------------------------------------------------------

    def _dblp(self, ref) -> _Answer:
        if not self.dblp_readable:
            # The mirror decides most confirmations, so a run without one is an incomplete run
            # and has to say so: `error` puts DBLP in `failed_dbs` and marks every reference
            # degraded. Reported as `skipped` instead -- a mistyped `$HALLUCITE_DBLP`, a half-built
            # file, a bot-check page written where the dump should be -- it would turn a whole
            # corpus into clean-looking `not_found`. Disable the backend to run without it.
            return _Answer(DbResult(DBLP, ERROR))
        title = getattr(ref, "title", "") or ""
        if not queryable(title):
            # Too short or too generic to ask about, so the mirror was never asked. `skipped` says
            # that; `no_match` would claim a search that did not happen.
            return _Answer(DbResult(DBLP, SKIPPED))
        started = time.monotonic()
        # The years the citation prints choose among records that already match, never whether
        # one does; a reference handed in without its text gets the published-first order alone.
        candidates = title_candidates(self.dblp_path, title,
                                      cited_years(getattr(ref, "raw_citation", "") or ""))
        elapsed = (time.monotonic() - started) * 1000
        records = [_Record(c.title, c.authors, f"https://dblp.org/rec/{c.key}") for c in candidates]
        return _answer(DBLP, ref, records, elapsed, self.dblp_authors_complete)

    def _crossref(self, ref) -> _Answer:
        title = (getattr(ref, "title", "") or "").strip()
        if not title:
            return _Answer(DbResult(CROSSREF, SKIPPED))
        names = [str(a) for a in (getattr(ref, "authors", None) or [])[:3]]
        started = time.monotonic()
        answer = _Answer(DbResult(CROSSREF, NO_MATCH))
        for form in _query_forms(title):
            params = {
                # `query.bibliographic` is the field CrossRef intends for a whole citation string,
                # and it tolerates the abbreviations and expansions an exact-title lookup misses.
                # Its relevance score is not usable as a threshold -- it is unnormalised and grows
                # with the query, and a fabricated title scores above a real one -- so the title
                # comparison below is what decides, over the top few hits.
                "query.bibliographic": " ".join([form] + names),
                "rows": "5",
                "select": "title,subtitle,author,DOI,update-to,updated-by",
            }
            if self.mailto:
                params["mailto"] = self.mailto
            payload, outcome = _fetch_json(f"{CROSSREF_WORKS}?{urllib.parse.urlencode(params)}",
                                           self.timeout, self.user_agent, self.rate_limit_retries)
            elapsed = (time.monotonic() - started) * 1000
            if outcome in DID_NOT_ANSWER:
                return _Answer(DbResult(CROSSREF, outcome, elapsed))
            if outcome != "ok":
                # `not_found` here is a 404 from the *search* endpoint, which says the endpoint is
                # gone, not that the work is. Folding it into `no_match` would report a clean
                # negative for every reference in the run.
                return _Answer(DbResult(CROSSREF, ERROR, elapsed))
            message = (payload or {}).get("message")
            # A search answer carries `items`, empty or not. A 200 without it is an error envelope,
            # not a result set, and reporting `no_match` for it would be a clean negative from a
            # request that told us nothing.
            if not isinstance(message, dict) or "items" not in message:
                return _Answer(DbResult(CROSSREF, ERROR, elapsed))
            items = message.get("items") or []
            answer = _answer(CROSSREF, ref, [_crossref_record(item) for item in items], elapsed)
            if answer.db_result.status != NO_MATCH:
                break
        return answer

    def _doi(self, ref) -> _Answer:
        doi = (getattr(ref, "doi", None) or "").strip()
        if not doi:
            return _Answer(DbResult(DOI, SKIPPED))
        started = time.monotonic()
        record, outcome = self._resolve_doi(doi)
        elapsed = (time.monotonic() - started) * 1000
        if outcome in DID_NOT_ANSWER:
            return _Answer(DbResult(DOI, outcome, elapsed))
        if record is None:
            # The registry answered and holds no such record: the DOI does not exist. It confirms
            # nothing, but a dead DOI is one of the fabrication signals triage weighs, so it is
            # recorded.
            return _Answer(DbResult(DOI, NO_MATCH, elapsed), doi_info=DoiInfo(doi, valid=False))
        answer = _answer(DOI, ref, [record], elapsed,
                         doi_info=DoiInfo(doi, valid=True, title=record.title or None))
        answer.db_result.paper_url = answer.db_result.paper_url or f"{DOI_ORG}{doi}"
        return answer

    def _resolve_doi(self, doi: str) -> tuple[_Record | None, str]:
        quoted = urllib.parse.quote(doi, safe="/:()<>;-._")
        payload, outcome = _fetch_json(f"{CROSSREF_WORKS}/{quoted}", self.timeout,
                                       self.user_agent, self.rate_limit_retries)
        if outcome == "ok" and payload:
            return _crossref_record(payload.get("message") or {}), "ok"
        if outcome in DID_NOT_ANSWER:
            return None, outcome
        # CrossRef holds only its own registrants' DOIs and answers 404 for every other registry's.
        # doi.org speaks for all of them, so a DataCite record -- a dataset, a Zenodo deposit, an
        # arXiv DOI -- is found only here.
        body, outcome = _fetch(f"{DOI_ORG}{quoted}", "application/vnd.citationstyles.csl+json",
                               max(self.timeout, _DOI_ORG_TIMEOUT), self.user_agent,
                               self.rate_limit_retries)
        if outcome == "not_found":
            return None, "ok"
        if outcome != "ok":
            return None, outcome
        try:
            return _csl_record(json.loads(body)), "ok"
        except (ValueError, UnicodeDecodeError):
            return None, ERROR

    def _arxiv(self, refs: list) -> list[_Answer]:
        """arXiv answers about a hundred identifiers in one request, so a whole residue costs a
        handful of calls rather than one each -- which matters, because its export API rate-limits
        a caller hard and stays shut for a long time afterwards.

        Two things it does quietly have to be undone here. A request that fails is reported as a
        failure for every identifier it carried: arXiv answers 200 with an empty feed for an
        identifier that does not exist, so absence and refusal look nothing alike from the outside,
        and reading a 429 as "no such preprint" would turn a rate limit into a fabrication signal.
        And a batch simply omits an identifier it will not serve -- an old-form id written with its
        subject class is dropped without a word -- so an identifier missing from a batch is asked
        for again on its own before it is called dead."""
        ids: list[str] = []
        for ref in refs:
            arxiv_id = _arxiv_key(getattr(ref, "arxiv_id", None) or "")
            if arxiv_id and arxiv_id not in ids:
                ids.append(arxiv_id)
        found: dict[str, _Record] = {}
        outcome_of: dict[str, str] = {}
        elapsed_of: dict[str, float] = {}
        for start in range(0, len(ids), _ARXIV_BATCH):
            chunk = ids[start:start + _ARXIV_BATCH]
            outcome, elapsed = self._ask_arxiv(chunk, found, pause=bool(start))
            for arxiv_id in chunk:
                outcome_of[arxiv_id] = outcome
                elapsed_of[arxiv_id] = elapsed

        # Asked for alone, an identifier a batch omitted either comes back or is really not there.
        absent = [i for i in ids if i not in found and outcome_of.get(i) == "ok"]
        rechecked = set(absent[:_ARXIV_RECHECK])
        for arxiv_id in absent[:_ARXIV_RECHECK]:
            outcome, elapsed = self._ask_arxiv([arxiv_id], found, pause=True)
            outcome_of[arxiv_id] = outcome
            elapsed_of[arxiv_id] = elapsed

        answers = []
        for ref in refs:
            cited = (getattr(ref, "arxiv_id", None) or "").strip()
            arxiv_id = _arxiv_key(cited)
            if not arxiv_id:
                answers.append(_Answer(DbResult(ARXIV, SKIPPED)))
                continue
            outcome = outcome_of.get(arxiv_id, ERROR)
            elapsed = elapsed_of.get(arxiv_id, 0.0)
            if outcome != "ok":
                answers.append(_Answer(DbResult(ARXIV, outcome, elapsed)))
                continue
            record = found.get(arxiv_id)
            if record is not None:
                answers.append(_answer(
                    ARXIV, ref, [record], elapsed,
                    arxiv_info=ArxivInfo(cited, valid=True, title=record.title or None)))
            elif arxiv_id in rechecked:
                answers.append(_Answer(DbResult(ARXIV, NO_MATCH, elapsed),
                                       arxiv_info=ArxivInfo(cited, valid=False)))
            else:
                # Beyond the re-check budget: nothing was confirmed and nothing is claimed.
                answers.append(_Answer(DbResult(ARXIV, NO_MATCH, elapsed)))
        return answers

    def _ask_arxiv(self, ids: list[str], found: dict[str, _Record],
                   pause: bool) -> tuple[str, float]:
        if pause:
            time.sleep(_ARXIV_PAUSE)
        params = {"id_list": ",".join(ids), "max_results": str(len(ids))}
        began = time.monotonic()
        body, outcome = _fetch(f"{ARXIV_API}?{urllib.parse.urlencode(params)}",
                               "application/atom+xml", self.timeout, self.user_agent,
                               self.rate_limit_retries)
        elapsed = (time.monotonic() - began) * 1000
        if outcome == "ok":
            entries = _arxiv_entries(body)
            if entries is None:
                return ERROR, elapsed         # a 200 that was not a feed is not an answer
            found.update(entries)
            return "ok", elapsed
        # A 400 means one identifier in the request was malformed, and arXiv rejects the whole
        # request for it: nothing in this batch was answered either.
        return (outcome if outcome in DID_NOT_ANSWER else ERROR), elapsed

    def _semantic_scholar(self, refs: list) -> list[_Answer]:
        """Semantic Scholar's paper search, over whatever the other four could not confirm.

        Asked one reference at a time and paced, because the pool is shared and small. It answers
        about work the other four do not index -- technical reports, theses, workshop papers --
        which is the whole reason it is here; it is also the slowest question hallucite asks, so it
        is asked last and only about the residue.

        Without a key it is not asked at all. Anonymous callers share one small quota: over 106
        real residue references, paced three and a half seconds apart, it refused 102 and confirmed
        none of the four it answered. Asking anyway would mark an arbitrary handful of references
        degraded and a different handful on the next run, which is the churn that moves the
        boundary between `verified` and "needs triage" between identical audits.

        A refusal is not an answer. Twenty-five in a row and the backend stops asking and reports
        the rest as `skipped`, because a rate limit that marked every remaining reference degraded
        would tell triage that no negative in the whole run is clean. Twenty-five however they
        fall is a different thing and gets a different answer: the backend is throttling rather
        than blocking, so it keeps being asked and simply stops being retried."""
        if not self.s2_api_key:
            return [_Answer(DbResult(SEMANTIC_SCHOLAR, SKIPPED)) for _ in refs]
        headers = {"x-api-key": self.s2_api_key}
        answers: list[_Answer] = []
        refused_in_a_row = refused_total = 0
        for i, ref in enumerate(refs):
            title = (getattr(ref, "title", "") or "").strip()
            if not title:
                answers.append(_Answer(DbResult(SEMANTIC_SCHOLAR, SKIPPED)))
                continue
            if refused_in_a_row >= _S2_GIVE_UP_AFTER:
                answers.append(_Answer(DbResult(SEMANTIC_SCHOLAR, SKIPPED)))
                continue
            # Throttling, not blocking: ask once and take the answer or the refusal.
            retries = (0 if refused_total >= _S2_PATIENCE
                       else max(self.rate_limit_retries, _S2_RETRIES))
            if i:
                time.sleep(_S2_PAUSE_KEYED)
            started = time.monotonic()
            answer, gave_up = _Answer(DbResult(SEMANTIC_SCHOLAR, NO_MATCH)), False
            for j, form in enumerate(_query_forms(title)):
                if j:
                    time.sleep(_S2_PAUSE_KEYED)
                params = {"query": form, "limit": "5", "fields": "title,authors,externalIds,url"}
                body, outcome = _fetch(f"{S2_SEARCH}?{urllib.parse.urlencode(params)}",
                                       "application/json", max(self.timeout, _S2_TIMEOUT),
                                       self.user_agent, retries, headers)
                elapsed = (time.monotonic() - started) * 1000
                if outcome in DID_NOT_ANSWER:
                    refused_in_a_row += 1
                    refused_total += 1
                    answers.append(_Answer(DbResult(SEMANTIC_SCHOLAR, outcome, elapsed)))
                    gave_up = True
                    break
                refused_in_a_row = 0
                if outcome != "ok":
                    # A 404 from the search endpoint says the endpoint moved, not that the work
                    # does not exist.
                    answer = _Answer(DbResult(SEMANTIC_SCHOLAR, ERROR, elapsed))
                    break
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    answer = _Answer(DbResult(SEMANTIC_SCHOLAR, ERROR, elapsed))
                    break
                # An answer carries `data`, empty or not. A 200 that carries only a message
                # ({"message": "Too Many Requests"}) is this backend's soft refusal, and reading it
                # as an empty result would report a clean negative and reset the counter above.
                if not isinstance(payload, dict) or "data" not in payload:
                    refused_in_a_row += 1
                    refused_total += 1
                    answers.append(_Answer(DbResult(SEMANTIC_SCHOLAR, RATE_LIMITED, elapsed)))
                    gave_up = True
                    break
                items = payload.get("data") or []
                answer = _answer(SEMANTIC_SCHOLAR, ref, [_s2_record(item) for item in items], elapsed)
                if answer.db_result.status != NO_MATCH:
                    break
            if not gave_up:
                answers.append(answer)
        return answers

    # -- the batch ------------------------------------------------------------

    def check(self, references: list) -> list[ValidationResult]:
        """One result per reference, in the input's order."""
        refs = list(references)
        results = [ValidationResult(status=NOT_FOUND) for _ in refs]
        if not refs:
            return results

        for name, run in ((DBLP, self._dblp), (CROSSREF, self._crossref), (DOI, self._doi),
                          (ARXIV, self._arxiv), (SEMANTIC_SCHOLAR, self._semantic_scholar)):
            if name in self.disabled:
                continue
            # Each backend is asked only about the references the ones before it did not match, so
            # the network cost falls on the residue a human will be asked to judge.
            pending = [i for i, r in enumerate(results)
                       if not any(d.status == MATCH for d in r.db_results)]
            batch = [refs[i] for i in pending]
            if name in (ARXIV, SEMANTIC_SCHOLAR):
                try:                                 # asked about the batch as a whole, so it is
                    answers = run(batch)             # guarded here rather than per reference
                except Exception:                    # noqa: BLE001
                    answers = [_Answer(DbResult(name, ERROR)) for _ in batch]
            else:
                answers = self._map(run, batch)
            for i, answer in zip(pending, answers):
                results[i].absorb(answer)
            for i in set(range(len(refs))) - set(pending):
                results[i].db_results.append(DbResult(name, SKIPPED))

        for result in results:
            self._finish(result)
        return results

    def _map(self, run, items: list) -> list:
        """Run one backend over its share of the batch.

        An unexpected exception becomes that reference's `error`, not the batch's. One malformed
        entry must not cost a paper its whole verification, and `error` is already the value that
        says "this backend did not answer about this reference"."""
        def guarded(item):
            try:
                return run(item)
            except Exception:                        # noqa: BLE001 -- reported, never re-raised
                return _Answer(DbResult(_backend_of(run), ERROR))

        if not items:
            return []
        if self.max_workers == 1 or len(items) == 1:
            return [guarded(item) for item in items]
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(guarded, items))

    @staticmethod
    def _finish(result: ValidationResult) -> None:
        result.failed_dbs = [d.db_name for d in result.db_results if d.status in DID_NOT_ANSWER]
        decisive = next((d for d in result.db_results if d.status == MATCH), None)
        if decisive is None:
            # No confirmation. A backend that found the cited title and disagreed about its authors
            # is the next most informative thing to report, and `mismatch` is the status that says
            # so without claiming the work was not found at all.
            decisive = next((d for d in result.db_results if d.status == AUTHOR_MISMATCH), None)
            result.status = MISMATCH if decisive is not None else NOT_FOUND
        else:
            result.status = VERIFIED
        if decisive is not None:
            result.source = decisive.db_name
            result.found_authors = list(decisive.found_authors)
            result.paper_url = decisive.paper_url


# An old-form identifier as arXiv's API takes it: the archive, not the subject class a citation
# prints. Asked for as "cs.SE/0303001" the record is omitted from the answer without comment; asked
# for as "cs/0303001" it comes back.
_ARXIV_SUBJECT_CLASS = re.compile(r"^([a-z-]+)\.[a-z]{2}/")


def _arxiv_key(arxiv_id: str) -> str:
    return _ARXIV_SUBJECT_CLASS.sub(r"\1/", re.sub(r"v\d+$", "", arxiv_id.strip().lower()))


def _arxiv_entries(body: bytes) -> dict[str, _Record] | None:
    """The feed's records by identifier, or None when the body was not a feed at all.

    The distinction is the whole point. arXiv answers 200 with an *empty* feed for an identifier it
    does not hold, and 200 with an HTML outage page when it is not serving -- and reading the
    second as the first turns a transport failure into "this preprint does not exist", which is
    fabrication signal (D) and, worse, leaves `failed_dbs` empty so the run looks complete. This is
    what `_fetch_json` already does for the JSON backends ("a JSON endpoint answering with HTML has
    not answered"); the XML path has to do it too."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    # Well-formed is not the same as an answer: an HTML outage page parses perfectly and carries no
    # entries, which is exactly what an identifier that does not exist looks like. The root tag is
    # what separates them.
    if root.tag != f"{_ATOM}feed":
        return None
    out: dict[str, _Record] = {}
    for entry in root.findall(f"{_ATOM}entry"):
        url = (entry.findtext(f"{_ATOM}id") or "").strip()
        key = _arxiv_key(url.rsplit("/abs/", 1)[-1]) if "/abs/" in url else ""
        title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
        if not key or not title:
            continue
        authors = [" ".join((a.findtext(f"{_ATOM}name") or "").split())
                   for a in entry.findall(f"{_ATOM}author")]
        out[key] = _Record(title=title, authors=[a for a in authors if a], url=url)
    return out


def check(references: list, **kwargs) -> list[ValidationResult]:
    """Verify a batch with a default configuration. `Verifier` takes the same keywords."""
    return Verifier(**kwargs).check(references)
