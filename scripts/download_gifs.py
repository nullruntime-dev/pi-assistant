#!/usr/bin/env python3
"""
Download funny GIFs from SFW subreddits into frontend/gifs/.

No auth needed — Reddit's public JSON endpoint.
Filters to direct .gif URLs (i.redd.it / i.imgur.com) under a size cap so
the kiosk doesn't choke loading them.

Re-run any time to refresh the collection. Existing files are skipped.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SUBREDDITS = [
    "reactiongifs",
    "gifs",
    "HighQualityGifs",
    "chemicalreactiongifs",
    "educationalgifs",
]
MAX_BYTES = 6 * 1024 * 1024          # skip anything bigger than 6 MB
TARGET_COUNT = 30                     # stop once we have this many
PER_SUB_LIMIT = 100                   # Reddit JSON cap per request
USER_AGENT = "pi-assistant/0.1 (by local user)"
GIFS_DIR = Path(__file__).resolve().parent.parent / "frontend" / "gifs"


def _fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _candidate_urls(sub: str) -> list[tuple[str, str]]:
    """Return (id, gif_url) pairs from r/{sub}/top.json."""
    url = f"https://www.reddit.com/r/{sub}/top.json?t=year&limit={PER_SUB_LIMIT}"
    try:
        data = _fetch_json(url)
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f"  ! {sub}: {e}", file=sys.stderr)
        return []

    out: list[tuple[str, str]] = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("over_18"):
            continue
        gif_url = post.get("url", "")
        # Only direct .gif hosts — skip v.redd.it (video), imgur albums, etc.
        if not gif_url.endswith(".gif"):
            continue
        if not ("i.redd.it" in gif_url or "i.imgur.com" in gif_url):
            continue
        post_id = post.get("id") or gif_url.rsplit("/", 1)[-1]
        out.append((f"{sub}_{post_id}", gif_url))
    return out


def _download(dest: Path, url: str) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            size = int(resp.headers.get("Content-Length") or 0)
            if size and size > MAX_BYTES:
                print(f"  ~ skip {dest.name} ({size // 1024} KB > cap)")
                return False
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                print(f"  ~ skip {dest.name} (>{MAX_BYTES // 1024} KB)")
                return False
            dest.write_bytes(data)
            return True
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  ! {url}: {e}", file=sys.stderr)
        return False


def main() -> int:
    GIFS_DIR.mkdir(parents=True, exist_ok=True)
    existing = {p.name for p in GIFS_DIR.glob("*.gif")}
    print(f"Target dir: {GIFS_DIR}  (have {len(existing)} already)")

    downloaded = 0
    for sub in SUBREDDITS:
        if len(existing) + downloaded >= TARGET_COUNT:
            break
        print(f"- r/{sub}")
        for post_id, gif_url in _candidate_urls(sub):
            if len(existing) + downloaded >= TARGET_COUNT:
                break
            filename = f"{post_id}.gif"
            if filename in existing:
                continue
            dest = GIFS_DIR / filename
            print(f"  + {filename}")
            if _download(dest, gif_url):
                downloaded += 1
                time.sleep(0.3)  # be polite to reddit/imgur

    # Regenerate the manifest so the frontend knows what's available.
    manifest = sorted(p.name for p in GIFS_DIR.glob("*.gif"))
    (GIFS_DIR / "index.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nDone. {downloaded} new, {len(manifest)} total in manifest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
