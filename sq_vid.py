"""Core media generation logic.

This module provides a function `generate_video` usable by a UI wrapper (web or GUI)
to create a square video from a YouTube audio segment and a static image.

Original script has been refactored so that side effects only occur when run as __main__.

TODO: 
Interface:
- Accept local file paths (or playlist?) for audio/image and then skip download steps if detected.
- Add progress bar to web UI
- If list/playlist provided, prompt user for time selection for each song before each clip is generated + batch download output files.

Backend:
- Setup so I can run from linux server and access web UI remotely.

"""

import yt_dlp
import requests
import uuid
import os
from pathlib import Path
from pathlib import Path
from typing import Any, Dict

# MoviePy v2 removed the 'moviepy.editor' namespace. Root-level imports are now recommended.
try:
    from moviepy import ImageClip, AudioFileClip  # v2 style
except ImportError as e:
    # Fallback for legacy v1 environments (should rarely trigger if v2 installed)
    try:
        from moviepy.editor import ImageClip, AudioFileClip  # type: ignore
    except Exception:
        raise ImportError(
            "MoviePy is not installed. Install with: pip install moviepy"
        ) from e

###############################
# Default configuration (used if running as script)
###############################
DEFAULT_AUDIO_URL = "https://www.youtube.com/watch?v=6IEfk8xJik0"
DEFAULT_IMAGE_URL = "https://i.discogs.com/Xtns2dtDEE-Q-nF_YTOgkkMGQ4aoPKRf80CW1xN9J10/rs:fit/g:sm/q:90/h:600/w:600/czM6Ly9kaXNjb2dz/LWRhdGFiYXNlLWlt/YWdlcy9SLTUyMTc4/NjktMTY3NjIxNjY1/Ny0xNjI4LmpwZWc.jpeg"
DEFAULT_OUTPUT_FILENAME = "fm_inc.mp4"
DEFAULT_START_TIME = 50.0
DEFAULT_CLIP_LENGTH = 30.0
DEFAULT_SQUARE_RES = 1080

def download_audio(url: str, stem: str = "temp_audio") -> Path:
    """Download audio from a YouTube URL robustly.

    1. Use yt_dlp with postprocessor to extract M4A.
    2. Derive final path from info dict after download.
    3. Fallback: if extracted file missing, retry without postprocessor then select first audio format URL.
    """
    # Primary attempt with postprocessor extraction
    outtmpl = f"{stem}.%(ext)s"
    primary_opts: Dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "ignoreerrors": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
                "preferredquality": "192",
            }
        ],
    }
    try:
        with yt_dlp.YoutubeDL(primary_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=True)
            # Try fields that may contain final filepath (varies by yt_dlp version)
            candidates = []
            if info:
                # requested_downloads newer API
                for req in info.get("requested_downloads", []):
                    fp = req.get("filepath") or req.get("_filename")
                    if fp:
                        candidates.append(fp)
                # legacy
                prepped = ydl.prepare_filename(info)
                if prepped:
                    # If postprocessor changed extension to m4a
                    if prepped.endswith(".webm") or prepped.endswith(".m4a") or prepped.endswith(".mp4"):
                        candidates.append(prepped.rsplit(".", 1)[0] + ".m4a")
                        candidates.append(prepped)
            for c in candidates:
                p = Path(c)
                if p.exists():
                    return p
    except Exception as e:
        print(f"Primary yt_dlp attempt failed: {e}")

    # Fallback raw download without postprocessors
    print("Primary audio extraction not found. Attempting fallback raw download...")
    fallback_opts: Dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(fallback_opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=True)
            if info:
                prepped = ydl.prepare_filename(info)
                if prepped and Path(prepped).exists():
                    return Path(prepped)
                # Direct URL fallback (stream) if file missing
                fmts = info.get("formats") or []
                for f in fmts:
                    if f.get("acodec") != "none" and f.get("url"):
                        # Stream to disk via requests
                        stream_url = f["url"]
                        target = Path(f"{stem}_raw.m4a")
                        try:
                            r = requests.get(stream_url, timeout=60, stream=True)
                            if r.status_code == 200:
                                with open(target, "wb") as fh:
                                    for chunk in r.iter_content(1024 * 32):
                                        if chunk:
                                            fh.write(chunk)
                                if target.exists() and target.stat().st_size > 0:
                                    return target
                        except Exception as e2:
                            print(f"Streaming fallback chunk failed: {e2}")
                        break
    except Exception as e:
        print(f"Fallback yt_dlp attempt failed: {e}")

    raise FileNotFoundError("Audio download failed; no file produced.")

def download_image(url: str, dest_stem: str = "cover") -> Path:
    """Robust image downloader.

    - Adds a User-Agent to avoid 403 blocks.
    - Streams to disk to avoid loading large files fully in memory.
    - Derives extension from Content-Type when possible.
    - Falls back to .jpg if unknown.
    - Validates non-empty content.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30, stream=True)
    except requests.RequestException as e:
        raise RuntimeError(f"Image download failed: {e}") from e

    if resp.status_code != 200:
        raise RuntimeError(f"Image download HTTP {resp.status_code} for {url}")

    content_type = resp.headers.get("Content-Type", "").lower()
    if "jpeg" in content_type:
        ext = ".jpg"
    elif "png" in content_type:
        ext = ".png"
    elif "webp" in content_type:
        ext = ".webp"
    else:
        # Attempt to infer from URL if header ambiguous
        for candidate in (".jpg", ".jpeg", ".png", ".webp"):
            if url.lower().endswith(candidate):
                ext = candidate if candidate != ".jpeg" else ".jpg"
                break
        else:
            ext = ".jpg"  # sensible default

    dest_path = Path(f"{dest_stem}{ext}")
    bytes_written = 0
    with open(dest_path, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                fh.write(chunk)
                bytes_written += len(chunk)

    if bytes_written == 0:
        raise RuntimeError("Downloaded image is empty.")

    return dest_path

def generate_video(
    audio_url: str,
    image_url: str,
    start_time: float,
    clip_length: float,
    output_filename: str,
    square_res: int = 1080,
) -> Path:
    """Generate a square video using given parameters.

    Returns path to the created video file.
    """
    start_time = max(0.0, start_time)
    requested_length = max(0.01, clip_length)
    square_res = max(64, square_res)

    # Use unique stems for temp files so repeated runs don't accidentally reuse
    # existing files from prior runs.
    unique_id = uuid.uuid4().hex
    audio_stem = f"temp_audio_{unique_id}"
    image_stem = f"cover_{unique_id}"

    print("Downloading audio via yt_dlp...")
    audio_path = download_audio(audio_url, stem=audio_stem)
    print(f"Audio saved to {audio_path}")

    print("Downloading image...")
    image_path = download_image(image_url, dest_stem=image_stem)
    print(f"Image saved to {image_path}")

    print("Combining media (building video clip)...")
    if not audio_path.exists():
        raise FileNotFoundError(f"Expected audio file not found: {audio_path}")
    raw_audio_clip = AudioFileClip(str(audio_path))

    audio_duration = getattr(raw_audio_clip, "duration", None)
    if audio_duration is None:
        print("Warning: audio duration unknown; proceeding with requested length.")
        effective_length = requested_length
    else:
        if start_time >= audio_duration:
            raise ValueError(
                f"Start time {start_time:.2f}s exceeds audio length {audio_duration:.2f}s"
            )
        remaining = audio_duration - start_time
        effective_length = min(requested_length, remaining)
        if requested_length > remaining:
            print(
                f"Requested length clipped to {effective_length:.2f}s (end of audio)."
            )

    end_time = start_time + effective_length

    # Extract segment
    if hasattr(raw_audio_clip, "subclipped"):
        audio_clip = raw_audio_clip.subclipped(start_time, end_time)  # v2
    else:
        audio_clip = raw_audio_clip.subclip(start_time, end_time)  # type: ignore[attr-defined]

    image_clip = ImageClip(str(image_path))
    if hasattr(image_clip, "with_duration"):
        image_clip = image_clip.with_duration(effective_length)
    else:
        image_clip = image_clip.set_duration(effective_length)  # type: ignore[attr-defined]

    if hasattr(image_clip, "resized"):
        image_clip = image_clip.resized(height=square_res).resized(width=square_res)
    else:
        image_clip = image_clip.resize(height=square_res).resize(width=square_res)

    if hasattr(image_clip, "with_audio"):
        video = image_clip.with_audio(audio_clip)
    else:
        video = image_clip.set_audio(audio_clip)

    print("Exporting video...")
    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_filename

    video.write_videofile(str(out_path), fps=30, codec="libx264", audio_codec="aac")

    # Ensure MoviePy releases file handles to ffmpeg so temp files can be removed
    for clip_obj, name in ((video, "video"), (audio_clip, "audio_clip"), (raw_audio_clip, "raw_audio_clip"), (image_clip, "image_clip")):
        try:
            if hasattr(clip_obj, "close"):
                clip_obj.close()
        except Exception as _:
            # Don't fail the whole run just because a close call misbehaves.
            pass

    # Remove temporary audio file so user can delete/move without needing to quit the shell.
    try:
        if audio_path.exists():
            # Only delete files that look like our generated temp stems to avoid
            # removing user-supplied files.
            if audio_stem in str(audio_path):
                audio_path.unlink()
    except Exception as e:
        print(f"Warning: couldn't remove temp audio file {audio_path}: {e}")

    print(
        f"✅ Done! Saved segment {start_time:.2f}s → {end_time:.2f}s ({effective_length:.2f}s) as {out_path}"
    )
    return out_path


if __name__ == "__main__":
    # Run with defaults when invoked directly.
    generate_video(
        DEFAULT_AUDIO_URL,
        DEFAULT_IMAGE_URL,
        DEFAULT_START_TIME,
        DEFAULT_CLIP_LENGTH,
        DEFAULT_OUTPUT_FILENAME,
        DEFAULT_SQUARE_RES,
    )
