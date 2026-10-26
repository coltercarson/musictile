# musictile

Make square music clips from your phone. Pick tracks from Navidrome, YouTube (a video or a whole playlist) or a local file, set each clip's start on a waveform, optionally swap the cover for one from Discogs, and render square MP4s (still cover + peak-normalised audio) to save straight to your phone.

## Setup

```bash
git clone https://github.com/coltercarson/musictile.git
cd musictile
cp .env.example .env
```

Fill in `.env`:

- `SECRET_KEY`: any long random string (`python3 -c "import secrets; print(secrets.token_hex(32))"`). It signs the login cookie, so keeping it fixed keeps you logged in across restarts.
- `DISCOGS_TOKEN` (optional): a personal token from <https://www.discogs.com/settings/developers>. Without it the Discogs cover search is off.
- `ND_URL` (optional): the Navidrome URL prefilled on the login form. Default `http://navidrome:4533`.

```bash
docker compose up -d --build
```

Open `http://coltersrv:5050` (or `http://<host>:5050`).

The compose file joins the external Docker network `navidrome_default` so the app can reach Navidrome by container name. If you don't run Navidrome in Docker on the same host, remove the `navidrome` network from `docker-compose.yml` and log in with Navidrome's normal URL.

The code is bind-mounted into the container: after editing Python, run `docker compose restart video-tile`. Edits to `static/` only need a page reload.

yt-dlp is baked into the image, so when YouTube stops working, update it with `docker compose build --no-cache && docker compose up -d`.

## Saving to the phone

**Save** uses Android's share sheet, so clips can go straight into Photos. Chrome only allows that on HTTPS. Over plain HTTP the app falls back to a normal download. To get the share sheet on HTTP, open `chrome://flags/#unsafely-treat-insecure-origin-as-secure` on the phone, add `http://coltersrv:5050`, and relaunch Chrome.

## Security

The app has no login of its own. Anyone who can reach port 5050 can use it, so keep it on your LAN or tailnet. Navidrome passwords are never stored on the server; the browser keeps one only if you tick "Save password".

## Tests

```bash
docker compose exec video-tile python test_render.py   # render + waveform
python3 e2e.py                                         # whole flow in a headless Pixel-sized Chrome (Playwright)
```

`e2e.py` runs on the host against the running app and uses the Local file source, so it needs no Navidrome login.

## Adding a source

1. Write a module exposing `fetch(ref, dest_dir) -> (audio_path, cover_path | None)`. If there's no cover, the server falls back to art embedded in the audio.
2. Add a branch for it in `app.py`'s `_fetch` and accept its name in `POST /api/tracks`, plus any routes its picker needs (listing, search).
3. Add a button on the Source step and a Select screen in `static/app.js`.

## License

MIT
