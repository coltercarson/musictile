# Video Tile Mobile + Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A phone-first web app that turns tracks from Navidrome, YouTube or local files into square MP4 clips, with waveform start-picking and Discogs cover swaps.

**Architecture:** One Flask app in Docker. Plain-module sources (`navidrome.py`, `youtube.py`, local upload) download audio + default cover into `data/cache/<key>/`; `waveform.py` caches peaks; `render.py` is one ffmpeg call; `static/index.html` + `static/app.js` is the whole UI. The UI is built first against a mock API and reviewed on a Pixel 9a before any backend exists.

**Tech Stack:** Python 3.12, Flask, yt-dlp (+ Deno for YouTube JS challenges), numpy, ffmpeg/ffprobe, stdlib `urllib`; vanilla JS/CSS; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-26-mobile-sources-design.md`

## Global Constraints

- HTTP calls use stdlib `urllib`; Python deps are only `flask`, `yt-dlp[default]`, `numpy`.
- Navidrome login: `POST {url}/auth/login`; keep `token`, `subsonicSalt`, `subsonicToken`; the server never stores the password. Like feishin, the browser remembers URL + username, and the password too when "Save password" is ticked (localStorage), and silently re-logs in once on a 401.
- Subsonic params: `c=video-tile`, `v=1.16.1`, `f=json`. Subsonic/cover/audio URLs never reach the browser.
- Waveform: 700 buckets, 8 kHz mono decode, JSON cache keyed by sha1 of `<source>:<ref>`.
- Render: center-crop square, 30 fps, `libx264 -tune stillimage`, peak-normalize to 0 dBFS, AAC 192k, `+faststart`.
- Defaults: clip length 30 s, resolution 1080.
- Docker: host port `5050` → container `5000`; joins external network `navidrome_default`; default `ND_URL=http://navidrome:4533`; reached at `http://coltersrv:5050`.
- Cache/output dirs older than 24 h are swept; `peaks/` is never swept.
- Output filenames are built server-side from `artist - title`, sanitized.
- No Flask debug mode. `SECRET_KEY` from env.
- Tests: `python test_render.py` (stdlib `unittest`), run inside the container.

## File map

| File | Status | Responsibility |
|------|--------|----------------|
| `Dockerfile`, `docker-compose.yml`, `.env.example`, `.gitignore`, `requirements.txt` | create/modify | Deployment |
| `app.py` | create | Flask routes, session, fetch pool, render jobs, sweep |
| `static/index.html`, `static/app.js` | create | UI (4 steps) |
| `static/mock.js` | create, then delete in Task 8 | Mock API for the prototype |
| `render.py` | create | ffmpeg: render, peak gain, embedded cover, mp3 preview |
| `waveform.py` | create | Peaks + cache (from tdz) |
| `navidrome.py` | create | Login, playlists, search, fetch |
| `youtube.py` | create | Lookup video/playlist, fetch audio + thumbnail |
| `discogs.py` | create | Release search, release images |
| `test_render.py` | create | Render + waveform tests |
| `sq_vid.py`, `video_ui.py` | delete in Task 8 | Replaced |
| `README.md` | modify in Task 8 | Usage |

## The API contract (shared by the mock and the real backend)

All JSON. Errors: `{"error": "..."}` with 4xx/5xx; Navidrome auth problems return 401 `{"error": "...", "login": true}`.

| Method + path | Body / query | Response |
|---|---|---|
| `GET /api/config` | | `{"nd_url": str, "nd_user": str\|null, "discogs": bool}` |
| `POST /api/nd/login` | `{"url","username","password"}` | `{"user": str}` |
| `POST /api/nd/logout` | | `{}` |
| `GET /api/nd/playlists` | | `[{"id","name","count"}]` |
| `GET /api/nd/playlists/<id>` | | `[Track]` |
| `GET /api/nd/search` | `?q=` | `[Track]` |
| `GET /api/yt/lookup` | `?url=` | `{"title": str, "tracks": [Track]}` |
| `POST /api/tracks` | JSON `{"source":"nd"\|"yt","ref"}` or multipart `source=local`, `file` | `{"key": str}` |
| `GET /api/tracks/<key>` | | `{"status": "fetching"\|"ready"\|"failed"\|"missing", "error"?: str, "duration"?: float}` |
| `GET /api/tracks/<key>/audio` | | audio file (Range supported) |
| `GET /api/tracks/<key>/peaks` | | `[float × 700]` |
| `GET /api/tracks/<key>/cover` | `?which=default\|custom` | image |
| `POST /api/tracks/<key>/cover` | JSON `{"url"}` or multipart `file` | `{}` |
| `GET /api/discogs/search` | `?q=` | `[{"title","year","thumb","cover","resource_url"}]` |
| `GET /api/discogs/images` | `?resource_url=` | `[url]` |
| `POST /api/render` | `{"length","res","items":[{"key","start","cover":"default"\|"custom","name"}]}` | `{"job": str}` |
| `GET /api/render/<job>` | | `{"items":[{"key","status":"queued"\|"rendering"\|"done"\|"failed","error"?,"url"?}]}` |
| `GET /output/<job>/<file>` | | mp4 download |

`Track` = `{"ref": str, "title": str, "artist": str, "album": str, "duration": number}`.

---

### Task 1: Docker scaffold serving static files

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.env.example`, `app.py`, `static/index.html` (placeholder)
- Modify: `requirements.txt`, `.gitignore`

**Interfaces:**
- Produces: container `video-tile` serving `static/` at `http://coltersrv:5050/`; `app` (Flask) in `app.py` that later tasks extend.

- [ ] **Step 1: Write deployment files**

`requirements.txt`:
```
flask
yt-dlp[default]
numpy
```

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# yt-dlp needs a JS runtime to solve YouTube's player challenges.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "app.py"]
```

`docker-compose.yml`:
```yaml
services:
  video-tile:
    build: .
    container_name: video-tile
    user: "1000:1000"
    ports:
      - "5050:5000"
    volumes:
      - .:/app   # ponytail: code is mounted, so `docker compose restart` picks up edits
    env_file:
      - path: .env
        required: false
    environment:
      HOME: /tmp
      ND_URL: ${ND_URL:-http://navidrome:4533}
    networks: [default, navidrome]
    restart: unless-stopped

networks:
  navidrome:
    external: true
    name: navidrome_default
```

`.env.example`:
```
SECRET_KEY=change-me
DISCOGS_TOKEN=
```

Append to `.gitignore`:
```
.env
data/
```

`app.py`:
```python
"""Video Tile: pick tracks from a source, set clip starts, render square videos."""
import os

from flask import Flask

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ["SECRET_KEY"]


@app.get("/")
def index():
    return app.send_static_file("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
```

`static/index.html`: `<!doctype html><title>Video Tile</title><p>scaffold ok</p>`

- [ ] **Step 2: Create `.env`**

```bash
cd /DATA/repositories/video-tile
printf 'SECRET_KEY=%s\nDISCOGS_TOKEN=%s\n' "$(python3 -c 'import secrets;print(secrets.token_hex(32))')" \
  "$(grep '^DISCOGS_TOKEN=' /DATA/repositories/tdz/.env | cut -d= -f2-)" > .env
```

- [ ] **Step 3: Build, start, verify**

Run: `docker compose up -d --build && sleep 3 && curl -s http://coltersrv:5050/`
Expected: `...scaffold ok...`

Run: `docker compose exec video-tile sh -c 'ffmpeg -version | head -1; deno --version | head -1; python -c "import yt_dlp, numpy; print(\"ok\")"'`
Expected: three lines, last is `ok`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml .env.example .gitignore requirements.txt app.py static/index.html
git commit -m "Docker scaffold serving static UI on :5050"
```

---

### Task 2: UI prototype with mock API → review on Pixel 9a

The UI is iterated with the user, so this task specifies behaviour and acceptance, not final markup.

**Files:**
- Create: `static/index.html`, `static/app.js`, `static/mock.js`

**Interfaces:**
- Produces: `app.js` talks only through an `api` object whose methods mirror the API contract table above. `mock.js` defines `window.mockApi` with the same methods, returning fixture data after a 300–800 ms delay. `app.js` uses `window.mockApi` when it exists, else the real fetch-based `api`.
- `api` methods: `config()`, `ndLogin(url, username, password)`, `ndLogout()`, `ndPlaylists()`, `ndPlaylist(id)`, `ndSearch(q)`, `ytLookup(url)`, `addTrack(source, ref)` → `{key}`, `uploadTrack(file)` → `{key}`, `track(key)`, `peaks(key)`, `audioUrl(key)`, `coverUrl(key, which)`, `discogsSearch(q)`, `discogsImages(resourceUrl)`, `setCoverUrl(key, url)`, `uploadCover(key, file)`, `render(payload)` → `{job}`, `job(id)`.

- [ ] **Step 1: Build `static/index.html`**: mobile viewport meta, `theme-color`, inline CSS tokens (dark default, light under `prefers-color-scheme: light`), bottom step bar (Source · Select · Clips (n) · Export) fixed with `env(safe-area-inset-bottom)` padding, one `<main>` that `app.js` renders into, a `<dialog>` for the cover sheet. Tap targets ≥ 44 px. Loads `mock.js` then `app.js`.

- [ ] **Step 2: Build `static/mock.js`**: fixtures: 4 playlists (one with 25 songs), search returning 8 songs for any query, a YouTube lookup that returns a 6-video playlist when the URL contains `list=` and a single video otherwise, peaks as a smoothed random envelope of 700 floats, track status `fetching` for ~1.5 s then `ready` (with one track that fails), Discogs search with 9 results using `https://picsum.photos/seed/<n>/300` images, render job that advances one item per second. `audioUrl` returns a short silent WAV data URL; `coverUrl` returns a picsum image.

- [ ] **Step 3: Build `static/app.js`**: state `{step, source, queue: [{key, source, ref, title, artist, album, status, duration, start, cover}], length: 30, res: 1080}` persisted to `localStorage` (wrapped in try/catch).
  - **Source:** three large buttons (Navidrome / YouTube / Local file) → sets source, goes to Pick.
  - **Pick / Navidrome:** login form when `config().nd_user` is null (URL prefilled from `nd_url`). Then a Playlists | Search segmented toggle. Playlist list → song list with per-row add (✓ when queued) and "Add all". Search: input with 300 ms debounce. Logout link.
  - **Pick / YouTube:** URL input + Look up. One result → added directly; a playlist → list UI identical to a Navidrome playlist.
  - **Pick / Local file:** `<input type=file accept="audio/*">` → `uploadTrack`.
  - Any add: push to queue with `status: "fetching"`, poll `track(key)` every 1.5 s until ready/failed. Step bar count updates.
  - **Clips:** length (number, s) and resolution (select 720/1080) at top. Per card: cover thumb (tap → cover sheet), title/artist, ✕ remove, canvas waveform (2× DPR, one bar per px, played part accent colour, clip window shaded, playhead line, "building waveform…" placeholder), play/pause, `m:ss / m:ss`, **Set start here**, start shown as `m:ss`. Tap/drag on the waveform seeks. One shared hidden `<audio>`; playing a card pauses others. Failed cards show the error and only ✕.
  - **Cover sheet:** tabs Default | Discogs | URL | Upload. Discogs: query prefilled `artist album`, grid of results, tap → images of that release, tap image → `setCoverUrl`. Hidden-with-note when `config().discogs` is false. Chosen cover marks `cover: "custom"` and the thumb refreshes.
  - **Export:** summary line, **Render** button (disabled while any track is fetching), per-track rows with status. Done rows get **Save**. **Save all** when all done. Save: if `navigator.canShare?.({files:[f]})` → `navigator.share({files})` with blobs fetched when the job finished (so the tap still has user activation); otherwise `<a download>` clicks.

- [ ] **Step 4: Point the browser at it**

Run: `docker compose restart video-tile && sleep 2 && curl -s http://coltersrv:5050/app.js | head -3`
Expected: first lines of `app.js`.

- [ ] **Step 5: Desktop check at Pixel 9a size**: Chrome devtools device mode 412×915: walk every step, every source, cover sheet, render, save. No horizontal scroll; console clean.

- [ ] **Step 6: Commit**

```bash
git add static/
git commit -m "UI prototype with mock API"
```

- [ ] **Step 7: USER REVIEW GATE.** Ask the user to open `http://coltersrv:5050/` on the Pixel 9a. Iterate until they approve. Note: `navigator.share` needs a secure context; on plain `http://coltersrv:5050` Chrome falls back to downloads unless the user adds the origin under `chrome://flags/#unsafely-treat-insecure-origin-as-secure`. Tell the user. Commit each round.

---

### Task 3: `render.py` + `waveform.py` with tests

**Files:**
- Create: `render.py`, `waveform.py`, `test_render.py`

**Interfaces:**
- Produces:
  - `render.RenderError(RuntimeError)`
  - `render.duration(path) -> float`
  - `render.peak_gain_db(audio, start: float, length: float) -> float`
  - `render.render(audio, image, start: float, length: float, res: int, out) -> Path`
  - `render.embedded_cover(audio, dest_dir: Path) -> Path | None` (writes `dest_dir/cover.jpg`)
  - `render.to_mp3(src, out) -> Path`
  - `waveform.WaveformError`, `waveform.PEAKS_DIR: Path`, `waveform.compute_peaks(source: str, buckets=700) -> list[float]`, `waveform.cached_peaks(key: str, source: str) -> list[float]`

- [ ] **Step 1: Write the failing tests** in `test_render.py`

```python
"""Render + waveform checks. Run: python test_render.py (needs ffmpeg/ffprobe)."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import render
import waveform


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.audio = self.tmp / "tone.flac"
        ff("-f", "lavfi", "-i", "sine=frequency=440:duration=10", "-af", "volume=-12dB", str(self.audio))
        self.image = self.tmp / "wide.png"  # non-square on purpose
        ff("-f", "lavfi", "-i", "color=c=red:s=640x360", "-frames:v", "1", str(self.image))


class RenderTests(Fixtures):
    def test_square_clip_with_audio_and_length(self):
        out = render.render(self.audio, self.image, 2, 5, 320, self.tmp / "out.mp4")
        info = probe(out)
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (320, 320))
        self.assertTrue(any(s["codec_type"] == "audio" for s in info["streams"]))
        self.assertAlmostEqual(float(info["format"]["duration"]), 5, delta=0.3)

    def test_output_peaks_at_zero_db(self):
        out = render.render(self.audio, self.image, 2, 5, 320, self.tmp / "out.mp4")
        self.assertLess(abs(render.peak_gain_db(out, 0, 5)), 1.0)

    def test_clip_stops_at_end_of_track(self):
        out = render.render(self.audio, self.image, 8, 5, 320, self.tmp / "end.mp4")
        self.assertAlmostEqual(float(probe(out)["format"]["duration"]), 2, delta=0.3)

    def test_start_past_end_raises(self):
        with self.assertRaises(render.RenderError):
            render.render(self.audio, self.image, 20, 5, 320, self.tmp / "x.mp4")

    def test_embedded_cover_missing_returns_none(self):
        self.assertIsNone(render.embedded_cover(self.audio, self.tmp))


class WaveformTests(Fixtures):
    def test_peaks_shape_and_cache(self):
        with patch.object(waveform, "PEAKS_DIR", self.tmp / "peaks"):
            peaks = waveform.cached_peaks("t:1", str(self.audio))
            self.assertEqual(len(peaks), 700)
            self.assertTrue(all(0 <= v <= 1 for v in peaks))
            with patch.object(waveform, "compute_peaks", side_effect=AssertionError("cache missed")):
                self.assertEqual(waveform.cached_peaks("t:1", str(self.audio)), peaks)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `docker compose exec video-tile python test_render.py`
Expected: `ModuleNotFoundError: No module named 'render'`

- [ ] **Step 3: Write `render.py`**

```python
"""ffmpeg helpers: square clip render, peak gain, embedded cover, mp3 preview."""
import re
import subprocess
from pathlib import Path


class RenderError(RuntimeError):
    pass


def _run(cmd):
    proc = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", *cmd], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RenderError(proc.stderr.strip()[-400:] or "ffmpeg failed")
    return proc


def duration(path) -> float:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise RenderError(f"Can't read audio length: {proc.stderr.strip()[:200]}") from exc


def peak_gain_db(audio, start: float, length: float) -> float:
    """Gain in dB that lifts the segment's peak to 0 dBFS."""
    proc = _run(["-ss", str(start), "-t", str(length), "-i", str(audio),
                 "-vn", "-af", "volumedetect", "-f", "null", "-"])
    match = re.search(r"max_volume: (-?[\d.]+) dB", proc.stderr)
    return -float(match.group(1)) if match else 0.0


def render(audio, image, start: float, length: float, res: int, out) -> Path:
    if start >= duration(audio):
        raise RenderError("Start is past the end of the track")
    gain = peak_gain_db(audio, start, length)
    vf = f"scale={res}:{res}:force_original_aspect_ratio=increase,crop={res}:{res},format=yuv420p"
    _run(["-y", "-v", "error",
          "-loop", "1", "-framerate", "30", "-i", str(image),
          "-ss", str(start), "-t", str(length), "-i", str(audio),
          "-map", "0:v", "-map", "1:a", "-vf", vf,
          "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
          "-af", f"volume={gain}dB", "-c:a", "aac", "-b:a", "192k",
          "-shortest", "-movflags", "+faststart", str(out)])
    return Path(out)


def embedded_cover(audio, dest_dir: Path):
    out = dest_dir / "cover.jpg"
    try:
        _run(["-y", "-v", "error", "-i", str(audio), "-an", "-frames:v", "1", str(out)])
    except RenderError:
        return None
    return out if out.exists() and out.stat().st_size else None


def to_mp3(src, out) -> Path:
    _run(["-y", "-v", "error", "-i", str(src), "-vn", "-c:a", "libmp3lame", "-q:a", "4", str(out)])
    return Path(out)
```

- [ ] **Step 4: Write `waveform.py`** (tdz `tdz/waveform.py`, config/log swapped out)

```python
"""Waveform peaks: one small amplitude envelope per track, computed once and cached.

Copied from tdz/waveform.py. ffmpeg decodes to 8 kHz mono, numpy buckets it,
and the few hundred floats are cached as JSON.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np

BUCKETS = 700
_RATE = 8000
PEAKS_DIR = Path(os.environ.get("DATA_DIR", "data")) / "peaks"


class WaveformError(Exception):
    """Raised when audio could not be decoded into an envelope."""


def _cache_file(key: str) -> Path:
    return PEAKS_DIR / f"{hashlib.sha1(key.encode()).hexdigest()}.json"


def compute_peaks(source: str, buckets: int = BUCKETS, timeout: int = 180) -> list[float]:
    """Decode ``source`` (a path) and return ``buckets`` peak amplitudes in 0..1."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", source,
           "-ac", "1", "-ar", str(_RATE), "-f", "f32le", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WaveformError(f"ffmpeg failed: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise WaveformError(proc.stderr.decode("utf-8", "replace").strip()[:200] or "no audio decoded")
    samples = np.frombuffer(proc.stdout, dtype="<f4")
    if samples.size < buckets:
        raise WaveformError("audio too short to bucket")
    trimmed = samples[: samples.size // buckets * buckets].reshape(buckets, -1)
    peaks = np.abs(trimmed).max(axis=1)
    ceiling = float(peaks.max()) or 1.0
    return [round(float(v) / ceiling, 4) for v in peaks]


def cached_peaks(key: str, source: str) -> list[float]:
    """Return the cached envelope for ``key``, computing and storing it on a miss."""
    path = _cache_file(key)
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    peaks = compute_peaks(source)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(peaks))
    except OSError as exc:  # a full or read-only cache must not break the app
        print(f"waveform cache write failed: {exc}")
    return peaks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec video-tile python test_render.py`
Expected: `Ran 6 tests ... OK`

- [ ] **Step 6: Commit**

```bash
git add render.py waveform.py test_render.py
git commit -m "ffmpeg render and waveform peaks with tests"
```

---

### Task 4: `navidrome.py`

**Files:**
- Create: `navidrome.py`

**Interfaces:**
- Produces: `NavidromeError(RuntimeError)`, `AuthExpired(NavidromeError)`, `login(url, username, password) -> dict` (session dict `{"url","user","jwt","salt","token"}`), `playlists(nd) -> [{"id","name","count"}]`, `playlist_tracks(nd, pid) -> [Track]`, `search(nd, q) -> [Track]`, `fetch(nd, song_id, dest: Path) -> (Path, Path | None)`. `nd` is the session dict; `_native` refreshes `nd["jwt"]` in place.

- [ ] **Step 1: Write `navidrome.py`**

```python
"""Navidrome client. Login follows feishin (/auth/login, keep the JWT + subsonic
salt/token, never the password); calls follow tdz/navidrome.py (stdlib urllib)."""
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
        if exc.code == 401:
            raise AuthExpired("Navidrome session expired, log in again") from exc
        raise NavidromeError(f"Navidrome {what} failed (HTTP {exc.code})") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise NavidromeError(f"Can't reach Navidrome: {getattr(exc, 'reason', exc)}") from exc


def login(url: str, username: str, password: str) -> dict:
    url = url.strip().rstrip("/")
    req = urllib.request.Request(
        f"{url}/auth/login", method="POST",
        data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with _open(req, "login") as resp:
            data = json.load(resp)
    except AuthExpired:
        raise NavidromeError("Wrong username or password") from None
    return {"url": url, "user": data["username"], "jwt": data["token"],
            "salt": data["subsonicSalt"], "token": data["subsonicToken"]}


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
        with open(path, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    return path


def fetch(nd: dict, song_id: str, dest: Path):
    """Original audio file + full-size cover into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    song = _subsonic(nd, "getSong", id=song_id)["song"]
    audio = _save(_subsonic_url(nd, "stream", id=song_id, format="raw"),
                  lambda _: dest / f"audio.{song.get('suffix') or 'bin'}")
    cover = None
    if song.get("coverArt"):
        cover = _save(_subsonic_url(nd, "getCoverArt", id=song["coverArt"]),
                      lambda ct: dest / f"cover{IMAGE_EXT.get(ct, '.jpg')}")
    return audio, cover
```

- [ ] **Step 2: Live check against Navidrome** (ask the user for a username/password, or have them run it)

```bash
docker compose exec video-tile python -c "
import getpass, navidrome, pathlib
nd = navidrome.login('http://navidrome:4533', input('user: '), getpass.getpass())
pls = navidrome.playlists(nd); print(len(pls), pls[:2])
songs = navidrome.playlist_tracks(nd, pls[0]['id']); print(songs[:1])
print(navidrome.search(nd, 'love')[:1])
print(navidrome.fetch(nd, songs[0]['ref'], pathlib.Path('/tmp/ndcheck')))
try: navidrome.login('http://navidrome:4533', 'nobody', 'x')
except navidrome.NavidromeError as e: print('bad login ->', e)
"
```
Expected: playlist count + dicts, a Track, two paths (`audio.<suffix>`, `cover.jpg`), `bad login -> Wrong username or password`.

- [ ] **Step 3: Commit**

```bash
git add navidrome.py && git commit -m "Navidrome client: feishin-style login, tdz-style calls"
```

---

### Task 5: `youtube.py` + `discogs.py`

**Files:**
- Create: `youtube.py`, `discogs.py`

**Interfaces:**
- Produces: `youtube.YouTubeError`, `youtube.lookup(url) -> {"title", "tracks": [Track]}`, `youtube.fetch(url, dest) -> (Path, Path | None)`; `discogs.DiscogsError`, `discogs.USER_AGENT`, `discogs.enabled() -> bool`, `discogs.search(q) -> [{"title","year","thumb","cover","resource_url"}]`, `discogs.images(resource_url) -> [str]`.

- [ ] **Step 1: Write `youtube.py`**

```python
"""YouTube source via yt-dlp: look up a video or playlist, download audio + thumbnail."""
from pathlib import Path

import yt_dlp

BASE = {"quiet": True, "no_warnings": True, "noprogress": True}


class YouTubeError(RuntimeError):
    pass


def lookup(url: str) -> dict:
    """Video or playlist URL -> {"title", "tracks"} without downloading anything."""
    try:
        with yt_dlp.YoutubeDL({**BASE, "skip_download": True, "extract_flat": "in_playlist"}) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeError(str(exc).removeprefix("ERROR: ")) from exc
    entries = info.get("entries")
    items = [e for e in entries if e] if entries is not None else [info]
    return {
        "title": info.get("title", "") if entries is not None else "",
        "tracks": [{"ref": f"https://www.youtube.com/watch?v={e['id']}", "title": e.get("title") or "",
                    "artist": e.get("channel") or e.get("uploader") or "", "album": "",
                    "duration": e.get("duration") or 0} for e in items],
    }


def fetch(url: str, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    opts = {**BASE, "format": "bestaudio/best", "noplaylist": True, "writethumbnail": True,
            "outtmpl": {"default": str(dest / "audio.%(ext)s"), "thumbnail": str(dest / "cover.%(ext)s")}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise YouTubeError(str(exc).removeprefix("ERROR: ")) from exc
    audio = next(dest.glob("audio.*"), None)
    if not audio:
        raise YouTubeError("yt-dlp produced no audio file")
    return audio, next(dest.glob("cover.*"), None)
```

- [ ] **Step 2: Write `discogs.py`** (trimmed from tdz `tdz/discogs.py`)

```python
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
```

- [ ] **Step 3: Live checks**

```bash
docker compose exec video-tile python -c "
import youtube, discogs, pathlib
print(youtube.lookup('https://www.youtube.com/watch?v=6IEfk8xJik0')['tracks'])
pl = youtube.lookup('https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI'); print(pl['title'], len(pl['tracks']))
print(youtube.fetch('https://www.youtube.com/watch?v=6IEfk8xJik0', pathlib.Path('/tmp/ytcheck')))
r = discogs.search('Aphex Twin Selected Ambient Works'); print(len(r), r[0]['title'])
print(discogs.images(r[0]['resource_url'])[:2])
"
```
Expected: one Track; a playlist title with >0 tracks; `(audio.webm|m4a, cover.webp|jpg)`; Discogs results and image URLs. If YouTube fails with a JS/challenge error, check `deno --version` in the container and upgrade yt-dlp (`docker compose build --no-cache`).

- [ ] **Step 4: Commit**

```bash
git add youtube.py discogs.py && git commit -m "YouTube (video + playlist) and Discogs cover search"
```

---

### Task 6: `app.py` API routes, fetch pool, render jobs

**Files:**
- Modify: `app.py` (full replacement below)

**Interfaces:**
- Consumes: everything from Tasks 3–5.
- Produces: the API contract table above.

- [ ] **Step 1: Replace `app.py`**

```python
"""Video Tile: pick tracks from a source, set clip starts, render square videos."""
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file, send_from_directory, session
from werkzeug.utils import secure_filename

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
    (d / "track.json").write_text(json.dumps({**_meta(d), **kw}))


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
        ext = Path(secure_filename(f.filename or "")).suffix.lower()
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
    for old in d.glob("custom.*"):
        old.unlink()
    if request.files.get("file"):
        f = request.files["file"]
        ext = Path(secure_filename(f.filename or "")).suffix.lower() or ".jpg"
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
        (d / f"custom{ext}").write_bytes(resp.read(25 * 1024 * 1024))
    return {}


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
    return {"items": [{k: v for k, v in it.items() if k in ("key", "status", "error", "url")}
                      for it in JOBS[job]["items"]]}


@app.get("/output/<job>/<path:name>")
def output_file(job, name):
    if not re.fullmatch(r"[0-9a-f]{32}", job):
        abort(404)
    return send_from_directory(OUTPUT / job, name, as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
```

- [ ] **Step 2: Restart and smoke-test with curl** (YouTube path needs no login)

```bash
docker compose restart video-tile && sleep 2
B=http://coltersrv:5050
curl -s $B/api/config
KEY=$(curl -s -H 'Content-Type: application/json' -d '{"source":"yt","ref":"https://www.youtube.com/watch?v=6IEfk8xJik0"}' $B/api/tracks | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
for i in $(seq 30); do S=$(curl -s $B/api/tracks/$KEY); echo "$S"; echo "$S" | grep -q fetching || break; sleep 2; done
curl -s $B/api/tracks/$KEY/peaks | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))'
curl -s -o /dev/null -w '%{http_code} %{content_type}\n' -H 'Range: bytes=0-99' $B/api/tracks/$KEY/audio
JOB=$(curl -s -H 'Content-Type: application/json' -d "{\"length\":10,\"res\":720,\"items\":[{\"key\":\"$KEY\",\"start\":30,\"name\":\"smoke test\"}]}" $B/api/render | python3 -c 'import sys,json;print(json.load(sys.stdin)["job"])')
sleep 15; curl -s $B/api/render/$JOB
curl -s $B/api/nd/playlists
```
Expected: config JSON with `"discogs": true`; status ends `ready` with a duration; `700`; `206 audio/...`; job item `done` with a `/output/...` URL; last call `401` JSON with `"login": true`.

- [ ] **Step 3: Run tests still pass**

Run: `docker compose exec video-tile python test_render.py`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app.py && git commit -m "API: sources, tracks, peaks, covers, render jobs"
```

---

### Task 7: Wire the UI to the real API

**Files:**
- Modify: `static/app.js`, `static/index.html`
- Delete: `static/mock.js`

**Interfaces:**
- Consumes: API contract table.

- [ ] **Step 1: Implement the real `api` object in `app.js`**: one `call(method, path, body)` helper: JSON body unless `body instanceof FormData`; on non-2xx parse `{error, login}` and throw an `Error` with `.login`. The prototype already wraps calls with the saved-password silent re-login and the `.login` → login-form handling; keep that wrapper and make the real `api` go through it. `audioUrl(key)` = `/api/tracks/${key}/audio`; `coverUrl(key, which)` = `/api/tracks/${key}/cover?which=${which}&t=${Date.now()}` (cache-bust after a change).

- [ ] **Step 2: Remove the mock**: delete `static/mock.js` and its `<script>` tag; drop the `window.mockApi` switch.

- [ ] **Step 3: On load, re-poll every queued track**: `missing` → card shows "expired, re-add" with ✕.

- [ ] **Step 4: Desktop pass at 412×915**: log in to Navidrome, add from a playlist and from search, add a YouTube playlist, upload a local file, change a cover via Discogs, render, save. Console clean.

- [ ] **Step 5: Commit**

```bash
git add -A static/ && git commit -m "UI talks to the real API"
```

---

### Task 8: Remove old code, README, phone end-to-end

**Files:**
- Delete: `sq_vid.py`, `video_ui.py`
- Modify: `README.md`

- [ ] **Step 1: Delete the old app**

```bash
git rm sq_vid.py video_ui.py
```

- [ ] **Step 2: Rewrite `README.md`**: what it does (one paragraph), setup (`cp .env.example .env`, fill `SECRET_KEY`/`DISCOGS_TOKEN`, `docker compose up -d --build`), open `http://coltersrv:5050`, tests (`docker compose exec video-tile python test_render.py`), the Chrome flag for the share sheet on plain HTTP, how to add a source (module with `fetch(...) -> (audio, cover)`, routes, a button, a Pick screen).

- [ ] **Step 3: Tests + restart**

Run: `docker compose restart video-tile && docker compose exec video-tile python test_render.py`
Expected: `OK`

- [ ] **Step 4: USER CHECK on the Pixel 9a**: full flow against live Navidrome, including a Discogs cover swap and Save all into Photos.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "Remove MoviePy app, update README"
```
