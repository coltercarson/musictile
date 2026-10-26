"""Navidrome client. Login follows feishin (/auth/login, keep the JWT + subsonic
salt/token, never the password); calls follow tdz/navidrome.py (stdlib urllib)."""
import http.client
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT, VERSION = "video-tile", "1.16.1"
IMAGE_EXT = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


class NavidromeError(RuntimeError):
    pass


class AuthExpired(NavidromeError):
    pass


def _open(req, what):
    try:
        return urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 401:
            raise AuthExpired("Navidrome session expired, log in again") from exc
        raise NavidromeError(f"Navidrome {what} failed (HTTP {exc.code})") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise NavidromeError(f"Can't reach Navidrome: {getattr(exc, 'reason', exc)}") from exc


def login(url: str, username: str, password: str) -> dict:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise NavidromeError("Server URL must start with http:// or https://")
    req = urllib.request.Request(
        f"{url}/auth/login", method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with _open(req, "login") as resp:
            data = json.load(resp)
        return {"url": url, "user": data["username"], "jwt": data["token"],
                "salt": data["subsonicSalt"], "token": data["subsonicToken"]}
    except AuthExpired:
        raise NavidromeError("Wrong username or password") from None
    except (ValueError, KeyError, TypeError) as exc:
        raise NavidromeError("That doesn't look like a Navidrome server") from exc


def _native(nd: dict, path: str):
    req = urllib.request.Request(nd["url"] + path, headers={"x-nd-authorization": f"Bearer {nd['jwt']}"})
    with _open(req, path) as resp:
        fresh = resp.headers.get("x-nd-authorization")
        if fresh:  # Navidrome slides the JWT expiry; keep the newest
            nd["jwt"] = fresh.removeprefix("Bearer ")
        return json.load(resp)


def _subsonic_url(nd: dict, endpoint: str, **params) -> str:
    query = urllib.parse.urlencode({**params, "u": nd["user"], "t": nd["token"], "s": nd["salt"],
                                    "v": VERSION, "c": CLIENT, "f": "json"})
    return f"{nd['url']}/rest/{endpoint}?{query}"


def _subsonic(nd: dict, endpoint: str, **params) -> dict:
    with _open(_subsonic_url(nd, endpoint, **params), endpoint) as resp:
        body = json.load(resp).get("subsonic-response") or {}
    if body.get("status") != "ok":
        err = body.get("error") or {}
        if err.get("code") == 40:
            raise AuthExpired("Navidrome rejected the saved login, log in again")
        raise NavidromeError(err.get("message") or f"Navidrome {endpoint} failed")
    return body


def _track(s: dict) -> dict:
    return {"ref": s["id"], "title": s.get("title", ""), "artist": s.get("artist", ""),
            "album": s.get("album", ""), "duration": s.get("duration", 0)}


def playlists(nd: dict) -> list[dict]:
    data = _native(nd, "/api/playlist?_sort=name&_order=ASC")
    return [{"id": p["id"], "name": p["name"], "count": p.get("songCount", 0)} for p in data]


def playlist_tracks(nd: dict, pid: str) -> list[dict]:
    pl = _subsonic(nd, "getPlaylist", id=pid).get("playlist") or {}
    return [_track(s) for s in pl.get("entry") or []]


def search(nd: dict, q: str) -> list[dict]:
    res = _subsonic(nd, "search3", query=q, songCount=50, artistCount=0, albumCount=0).get("searchResult3") or {}
    return [_track(s) for s in res.get("song") or []]


def _save(url: str, path_for) -> Path:
    with _open(url, "download") as resp:
        ctype = resp.headers.get_content_type()
        if ctype in ("application/json", "text/xml", "application/xml"):
            raise NavidromeError("Navidrome refused the download")
        path = path_for(ctype)
        part = path.with_name(path.name + ".part")
        try:
            with open(part, "wb") as fh:
                shutil.copyfileobj(resp, fh)
                expected = resp.headers.get("Content-Length")
                # http.client does not raise on a short body; check the length ourselves
                if expected is not None and fh.tell() != int(expected):
                    raise http.client.IncompleteRead(b"")
        except (OSError, http.client.HTTPException) as exc:
            part.unlink(missing_ok=True)
            raise NavidromeError("Navidrome download was interrupted") from exc
        part.replace(path)
    return path


def fetch(nd: dict, song_id: str, dest: Path):
    """Original audio file + full-size cover into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    song = _subsonic(nd, "getSong", id=song_id)["song"]
    suffix = song.get("suffix") or ""
    if not suffix.isalnum():  # server-supplied; keep it out of the filename
        suffix = "bin"
    audio = _save(_subsonic_url(nd, "stream", id=song_id, format="raw"),
                  lambda _: dest / f"audio.{suffix}")
    cover = None
    if song.get("coverArt"):
        cover = _save(_subsonic_url(nd, "getCoverArt", id=song["coverArt"]),
                      lambda ct: dest / f"cover{IMAGE_EXT.get(ct, '.jpg')}")
    return audio, cover
