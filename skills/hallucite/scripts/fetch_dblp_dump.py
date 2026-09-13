"""Fetch `dblp.xml.gz` with a real browser, for `mise run build-dblp`.

dblp.org and both its mirrors front the dump with an Anubis proof-of-work challenge. Every plain
HTTP client, `curl` among them, receives the challenge page instead of the file, and an ingest
reads it as zero publications -- so a working mirror is silently replaced by an empty one.

A browser answers that challenge with its own JS engine, the same way it does for a person clicking
the link. Nothing here forges or replays a token, and nothing disguises the client: Playwright's
usual `--enable-automation` marker is left in place. The one thing that matters is that the browser
runs headed -- Anubis refuses the headless build outright ("Access Denied"), while the headed one
completes the proof-of-work normally. So this needs a machine with a display; on a headless host,
download the dump on a desktop and copy it over.

One file, one request, no retry loop. DBLP publishes this dump precisely for building local
databases, which is the whole of what it is used for here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GZ = "https://dblp.org/xml/dblp.xml.gz"
LANDING = "https://dblp.org/xml/"


def default_dest() -> Path:
    """Beside the database the dump is built into, so relocating one relocates the other."""
    db = os.environ.get("HALLUCITE_DBLP")
    parent = Path(db).expanduser().parent if db else Path.home() / "hallucite"
    return parent / "dblp.xml.gz"


def body_text(page) -> str:
    try:
        return " ".join(page.inner_text("body").split())[:400]
    except Exception:
        return "(no body)"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("fetch-dblp-dump needs Playwright:\n"
              "  pip install playwright && playwright install chromium", file=sys.stderr)
        return 3

    dest = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else default_dest()
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

        if "noes" in page.title().lower() or "denied" in body_text(page).lower():
            print(f"refused: {body_text(page)}", file=sys.stderr)
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
        # Downloaded beside the destination and swapped in only once it is a gzip, the way
        # `build-dblp` swaps its database. Saving straight over `dest` overwrites the dump
        # you already have before finding out what arrived, and the failure this script
        # exists to catch -- the
        # challenge page under a .gz name -- is exactly when that matters.
        scratch = dest.with_name(dest.name + ".part")
        dl.value.save_as(scratch)
        browser.close()

    with open(scratch, "rb") as fh:
        magic = fh.read(2)
    if magic != b"\x1f\x8b":
        print(f"{scratch} is not gzip ({magic!r}) -- the challenge page was saved instead of the "
              f"dump. {dest} is untouched and nothing was ingested.", file=sys.stderr)
        scratch.unlink(missing_ok=True)
        return 1
    scratch.replace(dest)

    print(f"saved {dest} ({dest.stat().st_size / 1e9:.2f} GB)")
    print(f"now run:  DBLP_XML_GZ={dest} mise run build-dblp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
