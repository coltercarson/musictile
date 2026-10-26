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
