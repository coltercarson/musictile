"""Video Tile: pick tracks from a source, set clip starts, render square videos."""
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory, session
from werkzeug.exceptions import HTTPException

import discogs
import navidrome
import render
import waveform
import youtube

DATA = Path(os.environ.get("DATA_DIR", "data"))
CACHE, OUTPUT = DATA / "cache", DATA / "output"
MAX_AGE = 24 * 3600
ND_URL = os.environ.get("ND_URL", "http://navidrome:4533")
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".webm", ".aif", ".aiff", ".wma", ".alac"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
BROWSER_AUDIO = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav", ".webm"}

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ["SECRET_KEY"]
app.config.update(SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=500 * 1024 * 1024,
                  PERMANENT_SESSION_LIFETIME=30 * 24 * 3600)

fetch_pool = ThreadPoolExecutor(max_workers=3)
render_pool = ThreadPoolExecutor(max_workers=1)  # ponytail: one render at a time; ffmpeg already uses all cores
JOBS: dict[str, dict] = {}  # ponytail: in-memory, a restart forgets running jobs (files survive in output/)


# ---------- helpers ----------

def _tdir(key: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        abort(404)
    d = CACHE / key
    if d.exists():
        os.utime(d)  # any use (status, audio, peaks, cover) keeps it from being swept
    return d


def _one(d: Path, stem: str):
    return next(iter(sorted(d.glob(f"{stem}.*"))), None)


def _meta(d: Path) -> dict:
    try:
        return json.loads((d / "track.json").read_text())
    except (OSError, ValueError):
        return {}


def _set_meta(d: Path, **kw):
    tmp = d / "track.json.tmp"
    tmp.write_text(json.dumps({**_meta(d), **kw}))
    os.replace(tmp, d / "track.json")


def _sweep():
    cutoff = time.time() - MAX_AGE
    for root in (CACHE, OUTPUT):
        for d in root.glob("*"):
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w\-. ()&,']+", "_", name).strip(" ._")[:120] or "clip"


def _nd() -> dict:
    nd = session.get("nd")
    if not nd:
        raise navidrome.AuthExpired("Log in to Navidrome first")
    return nd


@app.after_request
def _keep_session(resp):
    if "nd" in session:
        session.modified = True  # navidrome._native refreshes the JWT inside the dict
    return resp


@app.errorhandler(navidrome.AuthExpired)
def _nd_expired(exc):
    session.pop("nd", None)
    return jsonify(error=str(exc), login=True), 401


@app.errorhandler(navidrome.NavidromeError)
@app.errorhandler(youtube.YouTubeError)
@app.errorhandler(discogs.DiscogsError)
@app.errorhandler(render.RenderError)
@app.errorhandler(urllib.error.URLError)  # custom cover URL that won't load
def _upstream(exc):
    return jsonify(error=str(exc)), 502


@app.errorhandler(ValueError)
def _bad(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(HTTPException)
def _http(exc):
    return jsonify(error=exc.description), exc.code


@app.errorhandler(Exception)
def _crash(exc):
    app.logger.exception(exc)
    return jsonify(error="Server error"), 500


# ---------- pages + config ----------

@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/config")
def config():
    return {"nd_url": ND_URL, "nd_user": (session.get("nd") or {}).get("user"), "discogs": discogs.enabled()}


# ---------- Navidrome ----------

@app.post("/api/nd/login")
def nd_login():
    body = request.get_json(force=True)
    session["nd"] = navidrome.login(body.get("url") or ND_URL, body.get("username", ""), body.get("password", ""))
    session.permanent = True  # survive browser restarts; the JWT inside still expires on Navidrome's schedule
    return {"user": session["nd"]["user"]}


@app.post("/api/nd/logout")
def nd_logout():
    session.pop("nd", None)
    return {}


@app.get("/api/nd/playlists")
def nd_playlists():
    return jsonify(navidrome.playlists(_nd()))


@app.get("/api/nd/playlists/<pid>")
def nd_playlist(pid):
    return jsonify(navidrome.playlist_tracks(_nd(), pid))


@app.get("/api/nd/search")
def nd_search():
    q = request.args.get("q", "").strip()
    return jsonify(navidrome.search(_nd(), q) if q else [])


# ---------- YouTube + Discogs ----------

@app.get("/api/yt/lookup")
def yt_lookup():
    return youtube.lookup(request.args.get("url", "").strip())


@app.get("/api/discogs/search")
def discogs_search():
    return jsonify(discogs.search(request.args.get("q", "").strip()))


@app.get("/api/discogs/images")
def discogs_images():
    return jsonify(discogs.images(request.args.get("resource_url", "")))


# ---------- tracks ----------

def _fetch(d: Path, source: str, ref: str, nd: dict | None):
    try:
        if source == "nd":
            audio, _ = navidrome.fetch(nd, ref, d)
        elif source == "yt":
            audio, _ = youtube.fetch(ref, d)
        else:
            audio = _one(d, "audio")
        if not _one(d, "cover"):
            render.embedded_cover(audio, d)
        if audio.suffix.lower() not in BROWSER_AUDIO:
            render.to_mp3(audio, d / "preview.mp3")
        waveform.cached_peaks(_meta(d)["peaks_key"], str(audio))
        _set_meta(d, status="ready", duration=render.duration(audio))
    except Exception as exc:  # any failure is shown on the track card
        _set_meta(d, status="failed", error=str(exc))


@app.post("/api/tracks")
def add_track():
    _sweep()
    key = uuid.uuid4().hex
    d = CACHE / key
    d.mkdir(parents=True)
    if request.files.get("file"):
        f = request.files["file"]
        ext = Path(f.filename or "").suffix.lower()
        if ext not in AUDIO_EXT:
            shutil.rmtree(d)
            raise ValueError(f"Unsupported audio type: {ext or 'unknown'}")
        f.save(d / f"audio{ext}")
        source, ref, nd = "local", key, None
    else:
        body = request.get_json(force=True)
        source, ref = body.get("source"), str(body.get("ref", ""))
        if source not in ("nd", "yt") or not ref:
            shutil.rmtree(d)
            raise ValueError("source must be nd or yt, with a ref")
        nd = dict(_nd()) if source == "nd" else None
    _set_meta(d, status="fetching", peaks_key=f"{source}:{ref}")
    fetch_pool.submit(_fetch, d, source, ref, nd)
    return {"key": key}


@app.get("/api/tracks/<key>")
def track_status(key):
    d = _tdir(key)
    if not d.exists():
        return {"status": "missing"}
    m = _meta(d)
    return {k: m[k] for k in ("status", "error", "duration") if k in m}


@app.get("/api/tracks/<key>/audio")
def track_audio(key):
    d = _tdir(key)
    path = _one(d, "preview") or _one(d, "audio")
    return send_file(path, conditional=True) if path else abort(404)


@app.get("/api/tracks/<key>/peaks")
def track_peaks(key):
    d = _tdir(key)
    audio = _one(d, "audio")
    if not audio:
        abort(404)
    return jsonify(waveform.cached_peaks(_meta(d)["peaks_key"], str(audio)))


@app.get("/api/tracks/<key>/cover")
def track_cover(key):
    d = _tdir(key)
    path = _one(d, "custom" if request.args.get("which") == "custom" else "cover")
    return send_file(path, max_age=0) if path else abort(404)


@app.post("/api/tracks/<key>/cover")
def set_cover(key):
    d = _tdir(key)
    if not d.exists():
        abort(404)
    if request.files.get("file"):
        f = request.files["file"]
        ext = Path(f.filename or "").suffix.lower()
        if ext not in IMAGE_EXT:
            raise ValueError("Cover must be a JPG, PNG, WebP or GIF image")
        _clear_custom(d)
        f.save(d / f"custom{ext}")
        return {}
    url = (request.get_json(force=True).get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Image URL must start with http(s)://")
    req = urllib.request.Request(url, headers={"User-Agent": discogs.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        ctype = resp.headers.get_content_type()
        if not ctype.startswith("image/"):
            raise ValueError("That URL isn't an image")
        ext = navidrome.IMAGE_EXT.get(ctype, ".jpg")
        data = resp.read(25 * 1024 * 1024)
    _clear_custom(d)
    (d / f"custom{ext}").write_bytes(data)
    return {}


def _clear_custom(d: Path):  # only once the new cover is known good, so a bad one keeps the old
    for old in d.glob("custom.*"):
        old.unlink()


# ---------- render ----------

def _render_job(job: str, length: float, res: int):
    out = OUTPUT / job
    out.mkdir(parents=True, exist_ok=True)
    for item in JOBS[job]["items"]:
        item["status"] = "rendering"
        try:
            d = CACHE / item["key"]
            audio = _one(d, "audio")
            cover = _one(d, "custom") if item["cover"] == "custom" else _one(d, "cover")
            if not audio:
                raise render.RenderError("Audio is gone (older than 24h?), re-add the track")
            if not cover:
                raise render.RenderError("No cover image, pick one")
            stem = _safe_name(item["name"])
            name, n = f"{stem}.mp4", 2
            while (out / name).exists():
                name, n = f"{stem} ({n}).mp4", n + 1
            render.render(audio, cover, float(item["start"]), length, res, out / name)
            item.update(status="done", url=f"/output/{job}/{name}")
        except Exception as exc:
            item.update(status="failed", error=str(exc))


@app.post("/api/render")
def start_render():
    _sweep()
    body = request.get_json(force=True)
    length = min(max(float(body.get("length", 30)), 1), 600)
    res = int(body.get("res", 1080))
    if res not in (720, 1080):
        raise ValueError("res must be 720 or 1080")
    items = []
    for it in body.get("items", []):
        _tdir(it["key"])  # validates the key
        items.append({"key": it["key"], "start": max(float(it.get("start", 0)), 0),
                      "cover": it.get("cover", "default"), "name": str(it.get("name", "clip")),
                      "status": "queued"})
    if not items:
        raise ValueError("Nothing to render")
    job = uuid.uuid4().hex
    JOBS[job] = {"items": items}
    render_pool.submit(_render_job, job, length, res)
    return {"job": job}


@app.get("/api/render/<job>")
def render_status(job):
    if job not in JOBS:
        abort(404)
    return {"items": [{k: v for k, v in dict(it).items() if k in ("key", "status", "error", "url")}
                      for it in JOBS[job]["items"]]}


@app.get("/output/<job>/<path:name>")
def output_file(job, name):
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        abort(404)
    return send_from_directory(OUTPUT / job, name, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
