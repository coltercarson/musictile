"""Minimal Flask UI wrapper for generate_video.

Run: python video_ui.py
Then open http://127.0.0.1:5000 in your browser.
"""

from flask import Flask, request, url_for, send_file, render_template_string
from pathlib import Path
from sq_vid import generate_video

app = Flask(__name__)

FORM_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Quick Video Generator</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 2rem; max-width: 800px; }
      form { display: grid; grid-template-columns: 150px 1fr; gap: .75rem 1rem; }
      label { font-weight: bold; }
      input[type=text], input[type=number] { width: 100%; padding: .4rem; }
      .full { grid-column: 1 / -1; }
      button { padding: .6rem 1.2rem; font-size: 1rem; }
      .msg { margin-top: 1rem; padding: .75rem; background:#eef; border:1px solid #99c; }
    </style>
  </head>
  <body>
    <h1>Quick Square Video Maker</h1>
    <form method="post" action="/generate">
      <label for="audio_url">YouTube URL</label>
      <input id="audio_url" name="audio_url" type="text" value="" required />
      <label for="image_url">Image URL</label>
      <input id="image_url" name="image_url" type="text" value="" required />
      <label for="start">Start (s)</label>
      <input id="start" name="start" type="number" step="0.01" value="0" min="0" />
      <label for="length">Length (s)</label>
      <input id="length" name="length" type="number" step="0.01" value="30" min="0.01" />
      <label for="resolution">Square Res</label>
      <input id="resolution" name="resolution" type="number" value="1080" min="64" />
      <label for="output">Output filename</label>
      <input id="output" name="output" type="text" value="output.mp4" />
      <div class="full"><button type="submit">Generate Video</button></div>
    </form>
    {% if message %}
      <div class="msg">{{ message|safe }}</div>
    {% endif %}
    {% if download_url %}
      <p><a href="{{ download_url }}">Download / View Video</a></p>
    {% endif %}
  </body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(FORM_HTML, message=None, download_url=None)


@app.post("/generate")
def generate():
    audio_url = request.form.get("audio_url", "").strip()
    image_url = request.form.get("image_url", "").strip()
    start = float(request.form.get("start", 0) or 0)
    length = float(request.form.get("length", 30) or 30)
    resolution = int(request.form.get("resolution", 1080) or 1080)
    output = request.form.get("output", "output.mp4").strip() or "output.mp4"

    try:
        video_path = generate_video(audio_url, image_url, start, length, output, resolution)
    except Exception as e:
        return render_template_string(
            FORM_HTML,
            message=f"<strong>Error:</strong> {e}",
            download_url=None,
        ), 400

    return render_template_string(
        FORM_HTML,
        message=f"Success! Generated {video_path.name} (start={start}s length={length}s).",
        download_url=url_for("download", filename=video_path.name),
    )


@app.get("/download/<filename>")
def download(filename: str):
    path = Path(filename)
    if not path.exists():
        return f"File not found: {filename}", 404
    return send_file(path, as_attachment=False)


if __name__ == "__main__":
    # Use threaded=True to allow handling multiple requests while encoding might block.
    app.run(debug=True, threaded=True)
