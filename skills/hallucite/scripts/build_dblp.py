#!/usr/bin/env python3
"""Build the offline DBLP mirror from the dump, with nothing but the standard library.

The mirror decides nine confirmations in ten, so this is the piece hallucite most needs to own.
It replaces `hallucinator-cli update-dblp`, and with it the Rust toolchain, the prebuilt binary,
and `dblp-entity-fix.patch` -- the patch existed because the stock ingest mangled the dump's
character entities and dropped every author whose name carries a diacritic, which is unsound in
exactly one direction: it reports an absence for references that are cited correctly.

    build_dblp.py <dblp.xml.gz> --out ~/hallucite/dblp.db

The dump is fronted by a bot challenge; `mise run fetch-dblp-dump` gets it with a real browser.

Two things carry the correctness.

**Entities.** dblp.xml declares its own HTML-style entities in dblp.dtd (`&auml;`, `&Ccedil;`,
`&eacute;`) and an XML parser given no DTD either fails on them or drops them. They are resolved
here, in the byte stream, before the parser sees them -- and a name that still cannot be resolved
keeps its text rather than losing the author, because a mangled name is a bad record and a missing
one is a bad *rule*: the author comparison reads an absence as a citation naming someone who is not
on the paper.

**Streaming.** The dump is ~4.5 GB of XML and ~8.7M records, so it is parsed incrementally and
every element is cleared as it is consumed; memory stays flat. The FTS index is built once at the
end, which is far cheaper than maintaining it per insert.
"""

from __future__ import annotations

import argparse
import gzip
import html.entities
import io
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# The record types that are publications. `www` is DBLP's person-homepage element and a handful of
# real "web resource" entries; the homepages are not publications and would otherwise put 3M
# titles like "Jane Doe" into the index, where a citation of a one-word title would find them.
KINDS = ("article", "inproceedings", "proceedings", "book", "incollection",
         "phdthesis", "mastersthesis")
# Where each kind keeps the venue.
VENUE_OF = {"article": "journal", "inproceedings": "booktitle", "incollection": "booktitle",
            "proceedings": "booktitle", "book": "publisher", "phdthesis": "school",
            "mastersthesis": "school"}

SCHEMA = """
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE publications (
    id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
    year INTEGER, venue TEXT, ee TEXT, kind TEXT, volume TEXT, number TEXT, pages TEXT);
CREATE TABLE publication_authors (
    pub_id INTEGER NOT NULL, author_id INTEGER NOT NULL, PRIMARY KEY (pub_id, author_id));
"""

# An entity reference the XML spec does not define itself. dblp's are the HTML4 set.
_ENTITY = re.compile(rb"&([A-Za-z][A-Za-z0-9]{1,31});")
_XML_BUILTIN = {b"amp", b"lt", b"gt", b"quot", b"apos"}


def _resolve(chunk: bytes) -> bytes:
    def one(m: "re.Match[bytes]") -> bytes:
        name = m.group(1)
        if name in _XML_BUILTIN:
            return m.group(0)
        code = html.entities.name2codepoint.get(name.decode("ascii"))
        # A *numeric* character reference, not the character's bytes: the dump declares
        # ISO-8859-1, so UTF-8 bytes spliced into it decode as Latin-1 and "Jürgen" arrives as
        # "JÃ¼rgen" -- the same mangled-name failure this script exists to avoid, one layer down.
        # A numeric reference means the same codepoint under any declared encoding.
        # An entity nobody declares is left as written; dropping it would silently rewrite a name.
        return b"&#%d;" % code if code else m.group(0)
    return _ENTITY.sub(one, chunk)


class _EntityStream(io.RawIOBase):
    """The dump with its named entities resolved, as a readable stream.

    Substituting in the byte stream rather than after parsing is what keeps the parser from ever
    seeing an undeclared entity. A chunk boundary that falls inside `&Ouml;` leaves half an entity
    on each side of it, so an `&` near the end of a chunk with no `;` after it is held back in
    `_tail` until the next chunk completes it. The held bytes are kept apart from `_out`, the
    resolved bytes waiting to be read: when they shared one buffer, a read that stopped a few bytes
    short of its end handed the parser `&uu` before `ml;` had arrived, and the build died on an
    undefined entity. `_pos` is how far `_out` has been read, so a read copies only what it returns
    rather than the whole remaining buffer."""

    def __init__(self, raw) -> None:
        self._raw = raw
        self._out = b""
        self._pos = 0
        self._tail = b""
        self._eof = False

    def readable(self) -> bool:
        return True

    def readinto(self, out) -> int:
        while len(self._out) - self._pos < len(out) and not self._eof:
            chunk = self._raw.read(1 << 20)
            if chunk:
                data = self._tail + chunk
                cut = data.rfind(b"&")
                if cut >= 0 and len(data) - cut <= 34 and b";" not in data[cut:]:
                    data, self._tail = data[:cut], data[cut:]
                else:
                    self._tail = b""
            else:
                self._eof = True
                data, self._tail = self._tail, b""
            self._out = self._out[self._pos:] + _resolve(data)
            self._pos = 0
        n = min(len(out), len(self._out) - self._pos)
        out[:n] = self._out[self._pos:self._pos + n]
        self._pos += n
        return n


def _text(elem, tag: str) -> str | None:
    child = elem.find(tag)
    if child is None:
        return None
    value = " ".join("".join(child.itertext()).split())
    return value or None


def build(dump: Path, out: Path, limit: int | None, progress_every: int) -> int:
    if out.exists():
        sys.exit(f"error: {out} exists. Build to a scratch path and swap it in once it is verified "
                 f"-- a half-written mirror reports every reference as not found.")
    con = sqlite3.connect(str(out))
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-200000;")
    con.executescript(SCHEMA)
    cur = con.cursor()

    authors: dict[str, int] = {}
    pubs = links = 0
    started = time.monotonic()
    stream = _EntityStream(gzip.open(dump, "rb"))
    # `recover`-style leniency is not available in the standard library, so the dump is trusted to
    # be well formed once its entities are resolved -- which, after they are, it is.
    # The root is cleared after every record. Clearing only the record left it attached to
    # <dblp>: on a synthetic dump of 400,000 records the empty records held there cost 37 MB of
    # peak memory, about 90 bytes per record.
    root = None
    for event, elem in ET.iterparse(stream, events=("start", "end")):
        if root is None:
            root = elem
        if event != "end" or elem.tag not in KINDS:
            continue
        key = elem.get("key") or ""
        title = _text(elem, "title")
        if key and title:
            pubs += 1
            cur.execute(
                "INSERT OR IGNORE INTO publications"
                "(id, key, title, year, venue, ee, kind, volume, number, pages)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pubs, key, title, _text(elem, "year"), _text(elem, VENUE_OF[elem.tag]),
                 _text(elem, "ee"), elem.tag, _text(elem, "volume"), _text(elem, "number"),
                 _text(elem, "pages")))
            # An edited book or a proceedings volume records its people in `<editor>`, and that is
            # who a citation of it names. Only where there is no author at all, so an edited
            # collection's editors never displace the chapter authors of the things inside it.
            people = elem.findall("author") or elem.findall("editor")
            for who in people:
                name = " ".join("".join(who.itertext()).split())
                if not name:
                    continue
                aid = authors.get(name)
                if aid is None:
                    cur.execute("INSERT OR IGNORE INTO authors(name) VALUES(?)", (name,))
                    aid = cur.lastrowid
                    authors[name] = aid
                cur.execute("INSERT OR IGNORE INTO publication_authors(pub_id, author_id) "
                            "VALUES(?,?)", (pubs, aid))
                links += 1
            if progress_every and pubs % progress_every == 0:
                rate = pubs / max(1e-6, time.monotonic() - started)
                print(f"  {pubs:>9,} publications, {len(authors):>9,} authors "
                      f"({rate:,.0f}/s)", flush=True)
            if limit and pubs >= limit:
                root.clear()
                break
        root.clear()

    print(f"  indexing {pubs:,} titles ...", flush=True)
    con.commit()
    con.executescript(
        "CREATE VIRTUAL TABLE publications_fts USING fts5"
        "(title, content='publications', content_rowid='id');"
        "INSERT INTO publications_fts(publications_fts) VALUES('rebuild');")
    con.executemany("INSERT OR REPLACE INTO metadata(key, value) VALUES(?,?)", [
        ("schema_version", "3"),
        ("last_updated", str(int(time.time()))),
        ("publication_count", str(pubs)),
        ("author_count", str(len(authors))),
        ("built_by", "hallucite build_dblp.py"),
    ])
    con.commit()
    con.close()
    accented = sum(1 for n in authors if any(ord(c) > 127 for c in n))
    took = time.monotonic() - started
    print(f"built {out}: {pubs:,} publications, {len(authors):,} authors, {links:,} authorships, "
          f"{accented:,} authors with a non-ASCII name, in {took / 60:.1f} min")
    # The one check that catches the failure this script exists to prevent. A mirror holding no
    # accented author at all was built by an ingest that dropped them, and every author comparison
    # over it is unsound in one direction.
    if pubs > 1000 and not accented:
        sys.exit("error: not one author name carries a non-ASCII character, so this build dropped "
                 "them. Do not swap this file in.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dump", type=Path, help="dblp.xml.gz (see: mise run fetch-dblp-dump)")
    p.add_argument("--out", type=Path, required=True, help="database to create (must not exist)")
    p.add_argument("--limit", type=int, default=None, help="stop after N publications (for a smoke build)")
    p.add_argument("--progress-every", type=int, default=500000)
    a = p.parse_args()
    if not a.dump.exists():
        sys.exit(f"error: {a.dump} not found. Get it with: mise run fetch-dblp-dump")
    return build(a.dump, a.out, a.limit, a.progress_every)


if __name__ == "__main__":
    raise SystemExit(main())
