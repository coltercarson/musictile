"""Discogs release search for alternative cover art. Throttle and 429 handling from tdz/discogs.py."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.discogs.com"
USER_AGENT = "video-tile/0.1 +https://github.com/coltercarson/video-tile"
INTERVAL, RATE_LIMIT_WAIT = 1.05, 65
_lock = threading.Lock()
_last = 0.0


class DiscogsError(RuntimeError):
    pass


def enabled() -> bool:
    return bool(os.environ.get("DISCOGS_TOKEN"))


def _throttle():
    global _last
    with _lock:
        wait = INTERVAL - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()


def _get(url: str, params: dict) -> dict:
    if not enabled():
        raise DiscogsError("DISCOGS_TOKEN is not set")
    query = urllib.parse.urlencode({**params, "token": os.environ["DISCOGS_TOKEN"]})
    req = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        _throttle()
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == 2:
                raise DiscogsError(f"Discogs returned HTTP {exc.code}") from exc
            retry = exc.headers.get("Retry-After")
            time.sleep(int(retry) if retry and retry.isdigit() else RATE_LIMIT_WAIT)
        except urllib.error.URLError as exc:
            raise DiscogsError(f"Can't reach Discogs: {exc.reason}") from exc
    raise DiscogsError("Discogs request failed")


def search(q: str) -> list[dict]:
    results = _get(f"{API}/database/search", {"q": q, "type": "release", "per_page": 24}).get("results", [])
    return [{"title": r.get("title", ""), "year": r.get("year", ""), "thumb": r.get("thumb", ""),
             "cover": r.get("cover_image", ""), "resource_url": r.get("resource_url", "")}
            for r in results if r.get("cover_image") and "spacer.gif" not in r["cover_image"]]


def images(resource_url: str) -> list[str]:
    if not resource_url.startswith(f"{API}/"):  # client-supplied: only ever call Discogs
        raise DiscogsError("Not a Discogs resource URL")
    return [i["uri"] for i in _get(resource_url, {}).get("images") or [] if i.get("uri")]
