# Video Tile revamp: mobile UI, sources, Navidrome

Date: 2026-10-26
Status: approved design, pre-implementation

## Goal

Make square music clips from a phone (Pixel 9a). Pick tracks from a source
(Navidrome first), choose each clip's start point by ear, optionally swap the
cover art for one found on Discogs, render on the server, and save the MP4s to
the phone.

## Scope

In:
- Mobile web UI with a four-step flow: Source → Select → Clips → Export.
- Sources: Navidrome (login, playlists, song search), YouTube (video or playlist URL), Local file (upload).
- Per-track start time chosen on a waveform (tap to seek, set start); one shared clip length.
- Cover picker: default cover, Discogs search, image URL, image upload.
- Server-side rendering with ffmpeg; save via Android share sheet.
- Runs in Docker, reached at `http://coltersrv:5050`.

Out (later):
- More sources (Discogs as an audio source, streaming playlists, server-side local library).
- Auto-picking a clip start.
- Native Android app.

## Process note: prototype the UI first

Before any backend work, build a clickable prototype of the full flow: the real
`static/index.html` + `app.js` with mock data (fake playlists, songs, YouTube playlist, waveform peaks, Discogs
results, render progress) and no server calls. Serve it from the server and
review it on the Pixel 9a (~412×915 CSS px viewport, Chrome). Iterate on layout
and flow until approved, then replace the mocks with API calls. The prototype is
the start of the production frontend, not a throwaway.

## Reused patterns

- **Navidrome login (from feishin, `src/renderer/api/navidrome/`):**
  `POST {server}/auth/login` with `{username, password}`. The response holds
  `token` (JWT for the native API), `subsonicSalt` and `subsonicToken`. Keep
  those; the server never stores the password. Like feishin, the login form remembers the server URL and username, and the password when "Save password" is ticked (browser localStorage); on 401 the page silently re-logs in once with a saved password before showing the form. Native API calls send
  `x-nd-authorization: Bearer <jwt>`; when a response carries a new
  `x-nd-authorization` header, replace the stored JWT. On 401, clear the session
  and return to the login form (feishin's behaviour when no password is saved).
- **Navidrome calls (from tdz, `tdz/navidrome.py`):** stdlib `urllib`,
  `NavidromeError`, `f=json`, `c=video-tile`, `v=1.16.1`. Subsonic responses with
  `status != "ok"` raise with Navidrome's message. Playlists from the native
  `/api/playlist`; playlist tracks from `getPlaylist.view`; search from
  `search3.view` (songs only); audio from `stream.view?format=raw`; covers from
  `getCoverArt.view`. Audio and covers are always fetched by the server, never
  linked from the page, because Subsonic URLs carry a credential.
- **Discogs (from tdz, `tdz/discogs.py`):** `database_search` with
  `type=release` (results include `cover_image`), `fetch_release_images` via the
  result's `resource_url`, `DISCOGS_TOKEN` from env, ~1 req/s throttle, retry on
  429 honouring `Retry-After`.

- **Waveforms (from tdz, `tdz/waveform.py` + `static/refine.js` `paintWave`):**
  copy `waveform.py` near-verbatim: ffmpeg decodes to 8 kHz mono f32, numpy
  buckets into 700 peak amplitudes normalized to 0..1, cached as JSON under a
  hashed key. Swap tdz's `get_audition_config`/`app_log` for a `PEAKS_DIR`
  constant and `print`. Draw on a 2× canvas the way `paintWave` does: one bar per
  pixel, played part in the accent colour, a playhead line. Reuse
  `tests/test_waveform.py`'s ffmpeg-tone approach for the test.
- **YouTube playlists:** yt-dlp `extract_info(url, download=False)` with
  `extract_flat: "in_playlist"` lists entries (id, title, duration) without
  downloading them.

## Architecture

```
phone (Chrome) ──HTTP──> Flask app (Docker, :5050)
                           ├── navidrome.py ──> http://navidrome:4533
                           ├── youtube.py   ──> yt-dlp
                           ├── discogs.py   ──> api.discogs.com
                           ├── render.py    ──> ffmpeg
                           └── cache/, output/  (volume)
```

### Files

| File | Purpose |
|------|---------|
| `app.py` | Flask routes, session, render job thread. Replaces `video_ui.py`. |
| `navidrome.py` | Login, playlists, playlist tracks, search, `fetch_audio`, `fetch_cover`. |
| `youtube.py` | yt-dlp download, moved from `sq_vid.py`; `list_playlist(url)`; `fetch_audio`, `fetch_cover` (thumbnail). |
| `waveform.py` | Peaks envelope + disk cache, copied from tdz. |
| `discogs.py` | Release search and release images for the cover picker. |
| `render.py` | `render(audio, image, start, length, res, out)`: one ffmpeg call. |
| `static/index.html`, `static/app.js` | The whole UI. Plain JS, no build step. |
| `test_render.py` | Render + waveform check (see Testing). |
| `Dockerfile`, `docker-compose.yml` | Deployment. |

`sq_vid.py`, `video_ui.py` and the MoviePy dependency are removed once their
code has moved.

### Source contract

Each source is a module exposing:

- `fetch(ref, dest_dir) -> (audio: Path, cover: Path | None)`

When a source has no cover, the server falls back to art embedded in the audio file.

`ref` is source-specific (Navidrome song id, YouTube URL, uploaded file token).
Picker endpoints are source-specific. Adding a source = one module, a few
routes, one picker screen, one button on the Source step.

### Track lifecycle

1. The user adds a track in Select. The page POSTs `{source, ref, title, artist, album}`.
2. The server assigns a track key, downloads audio and default cover into
   `cache/<key>/`, and reports ready or failed.
3. Once audio is cached, the server computes its waveform peaks
   (`waveform.cached_peaks`, key `<source>:<ref>`, e.g. `nd:<song id>` or
   `yt:<video id>`). The Clips step fetches peaks as JSON and plays
   `cache/<key>/audio` via `send_file` (Range/seek support built in), so there's
   no stream proxying.
4. Export POSTs the list of `{key, start, cover}` plus shared length/resolution.
   One background thread renders tracks in order into `output/`; the page polls
   per-track status.

The queue (track keys, metadata, start, chosen cover) lives in the browser in
`localStorage` so a refresh keeps it. Files in `cache/` and `output/` older than
24h are deleted when a new track is added or a render starts. Peaks live in a
separate `peaks/` dir that is not swept: they're a few KB each and re-adding a
song should reuse them.

### Session

Flask signed, permanent (30-day) session cookie (HttpOnly, `SameSite=Lax`) holds Navidrome
`url`, `username`, `jwt`, `subsonicSalt`, `subsonicToken`. `SECRET_KEY` comes
from env so restarts keep you logged in. Debug mode is off.

## UI flow

A step bar at the bottom: **Source · Select · Clips (n) · Export**. Any step
can be revisited; the queue persists across them.

1. **Source**: large buttons: Navidrome, YouTube, Local file.
2. **Select**: depends on the source.
   - Navidrome: login form if there's no session (server URL prefilled from
     `ND_URL` env, default `http://navidrome:4533`; username; password). Then a
     Playlists / Search toggle. Playlists → tap one → song list with
     tap-to-add, "Select all" and "Deselect all". Search → song results with tap-to-add.
   - YouTube: URL field. A video URL adds that video. A playlist URL (or a
     watch URL with `list=`) shows the playlist's videos in the same list UI
     as a Navidrome playlist: tap-to-add, "Select all" and "Deselect all".
   - Local file: audio file input + Add.
   Added tracks show a tick; the step bar count updates.
3. **Clips**: shared length (default 30s) and resolution (default 1080) at the
   top. One card per track: cover thumbnail, title/artist, remove button, and a
   waveform with play/pause and time display. The clip window
   (start → start + length) is shaded on the waveform; tap the waveform to
   set the clip start there (drag adjusts it); play from start
   previews the clip. Placeholder "building waveform…" until peaks arrive. Tapping the cover
   opens the cover picker sheet:
   - Default cover (Navidrome art / embedded art / YouTube thumbnail).
   - Discogs: query prefilled "artist album" (editable), grid of
     `cover_image` results; tapping a result shows all of its images.
   - Image URL field.
   - Image upload.
   The chosen cover is downloaded/stored server-side under the track's cache dir.
4. **Export**: **Render** button, per-track progress/status, then **Save** per
   track and **Save all**. Save uses `navigator.share({files})` when
   `navigator.canShare` allows files; otherwise a download link.

## Rendering

`render.py` runs ffmpeg directly:

- Input: looped still image + audio from `start` for `length` seconds (clipped
  to the end of the track).
- Video: scale to cover, center-crop to `res×res`, `yuv420p`, 30 fps, `libx264
  -tune stillimage`.
- Audio: peak-normalize to 0 dBFS (`volumedetect` pass on the segment, then
  `volume=<gain>dB`), AAC 192k.
- `-shortest`, `+faststart`.

Center-crop replaces the old resize-height-then-width, which stretched non-square covers.

## Errors

- Login: show Navidrome's error message (or "can't reach server").
- 401 from Navidrome: clear session, show login form, keep the queue.
- Track add failure: card shows failed with the reason and a remove button.
- Render failure: that track shows failed; the rest continue.
- Discogs without `DISCOGS_TOKEN`: the Discogs tab says it's not configured.
- Output filenames are generated server-side (`artist - title.mp4`, sanitized); no user-supplied paths.

## Testing

- `test_render.py`: generate a sine tone and a non-square image with ffmpeg
  `lavfi`, render a 5s clip from 2s, assert with `ffprobe`: video is res×res,
  there's an audio stream, duration ≈ 5s. Also: `compute_peaks` on the tone
  returns 700 values in 0..1, and a second `cached_peaks` call reads the
  cache. Runnable with plain `python test_render.py`.
- Manual: full flow on the Pixel 9a against the live Navidrome, including
  Discogs cover swap and Save all to Photos.

## Deployment

- `Dockerfile`: `python:3.12-slim`, `apt-get install ffmpeg`, `pip install -r
  requirements.txt` (flask, yt-dlp, numpy; HTTP calls use stdlib `urllib`), run `python app.py`
  on `0.0.0.0:5000`.
- `docker-compose.yml`: port `5050:5000`; joins the external
  `navidrome_default` network (Navidrome only listens on localhost and the
  Tailscale IP); volume for `cache/`, `output/` and `peaks/`; env `SECRET_KEY`,
  `DISCOGS_TOKEN`, `ND_URL`; `restart: unless-stopped`.
- Reached at `http://coltersrv:5050`.
