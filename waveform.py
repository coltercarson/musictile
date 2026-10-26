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
