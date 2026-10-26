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
