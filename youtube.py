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
