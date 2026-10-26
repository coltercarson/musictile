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
