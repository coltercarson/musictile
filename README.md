# Video Tile

Generate square videos from audio (YouTube or local files) and static images — perfect for sharing music clips on social media.

## Features

- 🎵 **YouTube audio download** — Extract audio directly from YouTube URLs
- 🖼️ **Flexible image sources** — Use a URL, local file, or embedded album art
- ✂️ **Clip trimming** — Specify start time and duration
- 🔊 **Audio normalization** — Automatically peaks audio to 0dB
- 📐 **Square output** — Configurable resolution (default 1080×1080)
- 🌐 **Web UI** — Simple Flask-based interface with drag-and-drop uploads

## Installation

```bash
# Clone the repository
git clone https://github.com/coltercarson/video-tile.git
cd video-tile

# Install dependencies
pip install -r requirements.txt
```

### Requirements

- Python 3.8+
- FFmpeg (must be available in PATH)

## Usage

### Web UI

```bash
python video_ui.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

### Command Line (Python API)

```python
from sq_vid import generate_video

generate_video(
    audio_url="https://www.youtube.com/watch?v=...",
    image_url="https://example.com/cover.jpg",
    start_time=30.0,       # Start at 30 seconds
    clip_length=60.0,      # 60 second clip
    output_filename="my_clip.mp4",
    square_res=1080,       # 1080x1080 output
)
```

#### Local Files

```python
generate_video(
    audio_url="",          # Ignored when audio_file is provided
    image_url="",          # Ignored when image_file is provided
    start_time=0.0,
    clip_length=30.0,
    output_filename="local_clip.mp4",
    audio_file="path/to/song.mp3",
    image_file="path/to/cover.jpg",
)
```

#### Embedded Album Art

```python
generate_video(
    audio_url="",
    image_url="",
    start_time=0.0,
    clip_length=30.0,
    output_filename="clip.mp4",
    audio_file="path/to/song.mp3",
    use_embedded_image=True,  # Extract cover art from audio file
)
```

## Output

Videos are saved to the `output/` directory as MP4 files (H.264 video, AAC audio).

## Dependencies

- [MoviePy](https://zulko.github.io/moviepy/) — Video editing
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube audio extraction
- [Flask](https://flask.palletsprojects.com/) — Web UI
- [Requests](https://requests.readthedocs.io/) — Image downloading

## License

MIT
