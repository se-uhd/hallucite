"""Fetch the dblp XML dump, for `mise run build-dblp`.

Two dumps exist and they are not the same file. dblp publishes a **monthly snapshot** through
Schloss Dagstuhl's DROPS: one release per month, each with its own DOI
(`10.4230/dblp.xml.2026-09-01`), released under CC0, served by an ordinary web server with an MD5
checksum beside it. dblp.org also publishes a **daily** dump, fronted by an Anubis proof-of-work
challenge that no plain HTTP client answers -- `curl` receives the challenge page instead of the
file, and an ingest reads that as zero publications, so a working mirror is silently replaced by
an empty one.

The snapshot is the default here for two reasons. A measurement can be repeated against it: "the
2026-09-01 release" names one fixed file forever, where "yesterday's dblp.xml.gz" names whatever
the crawler held that afternoon -- and this repo's measurement artifacts are sampled from a
particular mirror, so which dump built it is part of the result. And the checksum says whether the
bytes arrived, where `build-dblp` otherwise has to infer that from the database it built.

What it costs is currency: a paper indexed last week is in the daily dump and not in a snapshot
dated the first of the month. `--daily` is there for exactly that, and it needs Playwright and a
display, because only a real browser answers the challenge.

    fetch_dblp_dump.py [dest]            # the newest monthly snapshot, checksummed
    fetch_dblp_dump.py [dest] --daily    # dblp.org's daily dump, through a browser
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

SNAPSHOT_BASE = "https://drops.dagstuhl.de/storage/artifacts/dblp/xml"
SNAPSHOT_COLLECTION = "https://doi.org/10.4230/dblp.xml"
GZ = "https://dblp.org/xml/dblp.xml.gz"
LANDING = "https://dblp.org/xml/"
USER_AGENT = "hallucite (dblp mirror build)"
# How far back to look for the newest snapshot. A release is dated the first of its month and
# appears during it, so for part of every month the current month's file does not exist yet and
# the newest is the month before.
_LOOKBACK_MONTHS = 6


def default_dest() -> Path:
    """Beside the database the dump is built into, so relocating one relocates the other."""
    db = os.environ.get("HALLUCITE_DBLP")
    parent = Path(db).expanduser().parent if db else Path.home() / "hallucite"
    return parent / "dblp.xml.gz"


def snapshot_url(day: dt.date) -> str:
    """The release dated the first of this day's month."""
    return f"{SNAPSHOT_BASE}/{day.year}/dblp-{day.year:04d}-{day.month:02d}-01.xml.gz"


def _month_before(today: dt.date, months_back: int) -> dt.date:
    year, month = today.year, today.month - months_back
    while month <= 0:
        year, month = year - 1, month + 12
    return dt.date(year, month, 1)


def newest_snapshot(today: dt.date, exists) -> str | None:
    """The most recent release that is actually published, newest month first."""
    for back in range(_LOOKBACK_MONTHS):
        url = snapshot_url(_month_before(today, back))
        if exists(url):
            return url
    return None


def expected_md5(text: str) -> str:
    """The hash out of a `<md5>  <filename>` checksum file, or "" if there is none."""
    parts = (text or "").split()
    return parts[0].strip().lower() if parts else ""


def accept(scratch: Path, digest: str, expected: str) -> str:
    """"" if this download may be swapped in, else why it may not.

    The checksum is the first question and the gzip magic the second, because a challenge page or
    an HTML error saved under a `.gz` name passes neither -- and that is the failure this script
    exists to catch, whichever dump it came from."""
    if expected and digest != expected:
        return f"checksum mismatch: got {digest}, the release says {expected}"
    with open(scratch, "rb") as fh:
        magic = fh.read(2)
    if magic != b"\x1f\x8b":
        return f"not gzip ({magic!r}): what arrived is not the dump"
    return ""


def install(scratch: Path, dest: Path, digest: str, checksum: str) -> str:
    """Put a finished download in place, or say why it must not go there.

    The check and the move live in one function so neither download path can take the move without
    the check: `accept` decides, and this is what both the snapshot and the daily download call."""
    refusal = accept(scratch, digest, checksum)
    if refusal:
        scratch.unlink(missing_ok=True)
        return refusal
    scratch.replace(dest)
    return ""


def _open(url: str, method: str = "GET"):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method=method), timeout=120)


def _exists(url: str) -> bool:
    try:
        with _open(url, "HEAD") as fh:
            return fh.status == 200
    except urllib.error.HTTPError:
        return False
    except OSError:
        return False


def _download(url: str, scratch: Path) -> str:
    """Stream the file to `scratch`, returning its MD5. Never writes over `dest` itself."""
    digest = hashlib.md5()
    with _open(url) as fh, open(scratch, "wb") as out:
        total = int(fh.headers.get("Content-Length") or 0)
        got = 0
        while chunk := fh.read(1 << 20):
            out.write(chunk)
            digest.update(chunk)
            got += len(chunk)
            if total and got % (1 << 26) < (1 << 20):
                print(f"  {got / 1e9:.2f} of {total / 1e9:.2f} GB", flush=True)
    return digest.hexdigest()


def fetch_snapshot(dest: Path) -> int:
    url = newest_snapshot(dt.date.today(), _exists)
    if url is None:
        print(f"no monthly snapshot found in the last {_LOOKBACK_MONTHS} months under "
              f"{SNAPSHOT_BASE}. The collection is at {SNAPSHOT_COLLECTION}; --daily fetches "
              f"dblp.org's daily dump instead.", file=sys.stderr)
        return 1
    print(f"downloading {url} (about 1 GB) ...", flush=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    scratch = dest.with_name(dest.name + ".part")
    digest = _download(url, scratch)
    checksum = ""
    try:
        with _open(url + ".md5") as fh:
            checksum = expected_md5(fh.read(200).decode("ascii", "replace"))
    except (urllib.error.HTTPError, OSError):
        print("note: the release publishes no checksum beside it; falling back to the gzip check",
              file=sys.stderr)
    refusal = install(scratch, dest, digest, checksum)
    if refusal:
        print(f"{scratch}: {refusal}. {dest} is untouched and nothing was ingested.",
              file=sys.stderr)
        return 1
    print(f"saved {dest} ({dest.stat().st_size / 1e9:.2f} GB), md5 {digest}"
          + (" as published" if checksum else ""))
    return 0


def _body_text(page) -> str:
    try:
        return " ".join(page.inner_text("body").split())[:400]
    except Exception:                                            # noqa: BLE001
        return "(no body)"


def fetch_daily(dest: Path) -> int:
    """dblp.org's daily dump, with a real browser.

    A browser answers the proof-of-work challenge with its own JS engine, the same way it does for
    a person clicking the link. Nothing here forges or replays a token and nothing disguises the
    client: Playwright's usual `--enable-automation` marker is left in place. The one thing that
    matters is that the browser runs headed -- Anubis refuses the headless build outright ("Access
    Denied"), while the headed one completes the proof-of-work normally."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("--daily needs Playwright:\n"
              "  uv pip install playwright && playwright install chromium\n"
              "The monthly snapshot needs nothing: drop --daily.", file=sys.stderr)
        return 3

    headless = os.environ.get("PW_HEADLESS", "0") == "1"
    channel = os.environ.get("PW_CHANNEL") or None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless, channel=channel)
        page = browser.new_context(accept_downloads=True).new_page()

        print(f"opening {LANDING} ...", flush=True)
        page.goto(LANDING, wait_until="domcontentloaded", timeout=180_000)
        if "not a bot" in page.title().lower():
            print("  answering the proof-of-work challenge ...", flush=True)
            page.wait_for_function(
                "() => !document.title.toLowerCase().includes('not a bot')", timeout=180_000)

        if "noes" in page.title().lower() or "denied" in _body_text(page).lower():
            print(f"refused: {_body_text(page)}", file=sys.stderr)
            if headless:
                print("Anubis refuses the headless browser; rerun without PW_HEADLESS=1.",
                      file=sys.stderr)
            browser.close()
            return 2

        print(f"downloading {GZ} (about 1 GB) ...", flush=True)
        with page.expect_download(timeout=3_600_000) as dl:
            page.evaluate(
                """(url) => {
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'dblp.xml.gz';
                    document.body.appendChild(a);
                    a.click();
                }""",
                GZ,
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Saved beside the destination and swapped in only once it is a gzip, the way `build-dblp`
        # swaps its database: saving straight over `dest` overwrites the dump you already have
        # before finding out what arrived, and the challenge page under a .gz name is exactly when
        # that matters.
        scratch = dest.with_name(dest.name + ".part")
        dl.value.save_as(scratch)
        browser.close()

    refusal = install(scratch, dest, "", "")
    if refusal:
        print(f"{scratch}: {refusal}. {dest} is untouched and nothing was ingested.",
              file=sys.stderr)
        return 1
    print(f"saved {dest} ({dest.stat().st_size / 1e9:.2f} GB)")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dest", nargs="?", type=Path, default=None,
                   help="where to write the dump (default: beside $HALLUCITE_DBLP)")
    p.add_argument("--daily", action="store_true",
                   help="take dblp.org's daily dump through a browser instead of the newest "
                        "monthly snapshot; needs Playwright and a display")
    a = p.parse_args()
    dest = (a.dest or default_dest()).expanduser()
    code = fetch_daily(dest) if a.daily else fetch_snapshot(dest)
    if code == 0:
        print(f"now run:  DBLP_XML_GZ={dest} mise run build-dblp")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
