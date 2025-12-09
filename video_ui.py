"""Minimal Flask UI wrapper for generate_video.

Run: python video_ui.py
Then open http://127.0.0.1:5000 in your browser.
"""

import os
import tempfile
import uuid
import json
import threading
from flask import Flask, request, url_for, send_file, render_template_string, Response, session
from pathlib import Path
from werkzeug.utils import secure_filename
from sq_vid import generate_video

app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB max upload

# Store for progress updates (job_id -> {status, progress, message, result})
job_status = {}

# Allowed file extensions
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'm4a', 'wav', 'flac', 'ogg', 'aac', 'wma', 'aiff', 'aif'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}


def allowed_audio_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS


def allowed_image_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS

FORM_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Quick Video Generator</title>
    <!-- Dropzone.js CSS -->
    <link rel="stylesheet" href="https://unpkg.com/dropzone@5/dist/min/dropzone.min.css" type="text/css" />
    <style>
      body { font-family: Arial, sans-serif; margin: 2rem; max-width: 800px; }
      .form-grid { display: grid; grid-template-columns: 150px 1fr; gap: .75rem 1rem; }
      label { font-weight: bold; }
      input[type=text], input[type=number] { width: 100%; padding: .4rem; box-sizing: border-box; }
      .full { grid-column: 1 / -1; }
      button[type=submit] { padding: .6rem 1.2rem; font-size: 1rem; }
      .msg { margin-top: 1rem; padding: .75rem; background:#eef; border:1px solid #99c; }
      .msg.error { background: #fee; border-color: #c99; }
      .msg.success { background: #efe; border-color: #9c9; }
      .section-header { grid-column: 1 / -1; margin-top: 1rem; padding-top: 0.5rem; border-top: 1px solid #ddd; font-size: 0.9rem; color: #666; }
      
      /* Progress bar styles */
      .progress-container {
        display: none;
        margin-top: 1.5rem;
        padding: 1rem;
        background: #f5f5f5;
        border-radius: 8px;
        border: 1px solid #ddd;
      }
      .progress-container.active {
        display: block;
      }
      .progress-bar-wrapper {
        background: #ddd;
        border-radius: 4px;
        height: 24px;
        overflow: hidden;
        margin-bottom: 0.5rem;
      }
      .progress-bar {
        height: 100%;
        background: linear-gradient(90deg, #4a90d9, #67b26f);
        border-radius: 4px;
        transition: width 0.3s ease;
        width: 0%;
      }
      .progress-text {
        font-size: 0.9rem;
        color: #666;
        text-align: center;
      }
      .progress-percent {
        font-weight: bold;
        color: #333;
      }
      .checkbox-row { display: flex; align-items: center; gap: 0.5rem; }
      .checkbox-row input[type=checkbox] { width: auto; }
      .or-divider { grid-column: 1 / -1; text-align: center; color: #888; font-style: italic; margin: 0.25rem 0; }
      .hint { font-size: 0.85rem; color: #666; font-weight: normal; }
      
      /* Custom dropzone styling */
      .dropzone {
        border: 2px dashed #ccc;
        border-radius: 8px;
        background: #fafafa;
        min-height: 80px;
        padding: 10px;
      }
      .dropzone:hover {
        border-color: #999;
        background: #f0f0f0;
      }
      .dropzone.dz-drag-hover {
        border-color: #4a90d9;
        background: #e8f4fc;
      }
      .dropzone .dz-message {
        margin: 1em 0;
      }
      .dropzone.has-file {
        border-color: #5a5;
        background: #efffef;
      }
      .file-input-wrapper {
        position: relative;
      }
      .file-input-wrapper input[type=file] {
        width: 100%;
        padding: 0.5rem;
        border: 2px dashed #ccc;
        border-radius: 8px;
        background: #fafafa;
        cursor: pointer;
      }
      .file-input-wrapper input[type=file]:hover {
        border-color: #999;
        background: #f0f0f0;
      }
    </style>
  </head>
  <body>
    <h1>Quick Square Video Maker</h1>
    <form id="mainForm" method="post" action="/generate" enctype="multipart/form-data">
      <div class="form-grid">
        <div class="section-header">Audio Source (provide URL or upload file)</div>
        
        <label for="audio_url">YouTube URL</label>
        <input id="audio_url" name="audio_url" type="text" value="" placeholder="https://www.youtube.com/watch?v=..." />
        
        <div class="or-divider">— or —</div>
        
        <label>Upload Audio</label>
        <div class="file-input-wrapper">
          <input id="audio_file" name="audio_file" type="file" accept=".mp3,.m4a,.wav,.flac,.ogg,.aac,.wma,.aiff,.aif" />
        </div>
        
        <div class="section-header">Image Source (provide URL, upload file, or use embedded)</div>
        
        <label class="checkbox-row">
          <input id="use_embedded_image" name="use_embedded_image" type="checkbox" onchange="toggleImageInputs()" />
          Use embedded image from audio file
        </label>
        <span class="hint">(Extract cover art from the audio file)</span>
        
        <label for="image_url">Image URL</label>
        <input id="image_url" name="image_url" type="text" value="" placeholder="https://example.com/image.jpg" />
        
        <div class="or-divider">— or —</div>
        
        <label>Upload Image</label>
        <div class="file-input-wrapper">
          <input id="image_file" name="image_file" type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.bmp" />
        </div>
        
        <div class="section-header">Video Settings</div>
        
        <label for="start">Start (s)</label>
        <input id="start" name="start" type="number" step="0.01" value="0" min="0" />
        <label for="length">Length (s)</label>
        <input id="length" name="length" type="number" step="0.01" value="30" min="0.01" />
        <label for="resolution">Square Res</label>
        <input id="resolution" name="resolution" type="number" value="1080" min="64" />
        <label for="output">Output filename</label>
        <input id="output" name="output" type="text" value="output.mp4" />
        <div class="full"><button type="submit" id="submitBtn">Generate Video</button></div>
      </div>
    </form>
    
    <div id="progressContainer" class="progress-container">
      <div class="progress-bar-wrapper">
        <div id="progressBar" class="progress-bar"></div>
      </div>
      <div class="progress-text">
        <span id="progressText">Preparing...</span>
        <span id="progressPercent" class="progress-percent">0%</span>
      </div>
    </div>
    
    <div id="messageContainer">
    {% if message %}
      <div class="msg">{{ message|safe }}</div>
    {% endif %}
    {% if download_url %}
      <p><a href="{{ download_url }}">Download / View Video</a></p>
    {% endif %}
    </div>
    
    <script>
      function toggleImageInputs() {
        const useEmbedded = document.getElementById('use_embedded_image').checked;
        const imageUrl = document.getElementById('image_url');
        const imageFile = document.getElementById('image_file');
        imageUrl.disabled = useEmbedded;
        imageFile.disabled = useEmbedded;
        if (useEmbedded) {
          imageUrl.style.opacity = '0.5';
          imageFile.style.opacity = '0.5';
        } else {
          imageUrl.style.opacity = '1';
          imageFile.style.opacity = '1';
        }
      }
      
      document.getElementById('mainForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const form = e.target;
        const formData = new FormData(form);
        const submitBtn = document.getElementById('submitBtn');
        const progressContainer = document.getElementById('progressContainer');
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');
        const messageContainer = document.getElementById('messageContainer');
        
        // Reset and show progress
        submitBtn.disabled = true;
        submitBtn.textContent = 'Processing...';
        progressContainer.classList.add('active');
        progressBar.style.width = '0%';
        progressText.textContent = 'Uploading...';
        progressPercent.textContent = '0%';
        messageContainer.innerHTML = '';
        
        try {
          // Start the job
          const response = await fetch('/generate', {
            method: 'POST',
            body: formData
          });
          
          const result = await response.json();
          
          if (result.job_id) {
            // Poll for progress
            pollProgress(result.job_id);
          } else if (result.error) {
            showError(result.error);
            resetForm();
          }
        } catch (error) {
          showError('Request failed: ' + error.message);
          resetForm();
        }
      });
      
      function pollProgress(jobId) {
        const progressBar = document.getElementById('progressBar');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');
        
        const poll = async () => {
          try {
            const response = await fetch('/progress/' + jobId);
            const data = await response.json();
            
            progressBar.style.width = data.progress + '%';
            progressText.textContent = data.message || 'Processing...';
            progressPercent.textContent = data.progress + '%';
            
            if (data.status === 'complete') {
              showSuccess(data.result.message, data.result.download_url);
              resetForm();
            } else if (data.status === 'error') {
              showError(data.error);
              resetForm();
            } else {
              // Continue polling
              setTimeout(poll, 500);
            }
          } catch (error) {
            showError('Failed to get progress: ' + error.message);
            resetForm();
          }
        };
        
        poll();
      }
      
      function showError(message) {
        const messageContainer = document.getElementById('messageContainer');
        messageContainer.innerHTML = '<div class="msg error"><strong>Error:</strong> ' + message + '</div>';
      }
      
      function showSuccess(message, downloadUrl) {
        const messageContainer = document.getElementById('messageContainer');
        let html = '<div class="msg success">' + message + '</div>';
        if (downloadUrl) {
          html += '<p><a href="' + downloadUrl + '">Download / View Video</a></p>';
        }
        messageContainer.innerHTML = html;
      }
      
      function resetForm() {
        const submitBtn = document.getElementById('submitBtn');
        const progressContainer = document.getElementById('progressContainer');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Generate Video';
        // Keep progress visible for a moment after completion
        setTimeout(() => {
          progressContainer.classList.remove('active');
        }, 2000);
      }
    </script>
  </body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(FORM_HTML, message=None, download_url=None)


@app.get("/progress/<job_id>")
def get_progress(job_id):
    """Return the current progress of a job."""
    if job_id not in job_status:
        return json.dumps({"status": "error", "error": "Job not found"}), 404
    return json.dumps(job_status[job_id])


def run_video_generation(job_id, audio_url, image_url, start, length, output, resolution,
                         audio_file_path, image_file_path, use_embedded_image, temp_files):
    """Background worker to generate video with progress updates."""
    def progress_callback(stage, percent):
        job_status[job_id] = {
            "status": "processing",
            "progress": percent,
            "message": stage
        }
    
    try:
        video_path = generate_video(
            audio_url=audio_url,
            image_url=image_url,
            start_time=start,
            clip_length=length,
            output_filename=output,
            square_res=resolution,
            audio_file=audio_file_path,
            image_file=image_file_path,
            use_embedded_image=use_embedded_image,
            progress_callback=progress_callback,
        )
        
        job_status[job_id] = {
            "status": "complete",
            "progress": 100,
            "message": "Done!",
            "result": {
                "message": f"Success! Generated {video_path.name} (start={start}s length={length}s).",
                "download_url": f"/download/{video_path.name}"
            }
        }
    except Exception as e:
        job_status[job_id] = {
            "status": "error",
            "progress": 0,
            "error": str(e)
        }
    finally:
        # Cleanup temp files
        for temp_dir in temp_files:
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass


@app.post("/generate")
def generate():
    audio_url = request.form.get("audio_url", "").strip()
    image_url = request.form.get("image_url", "").strip()
    start = float(request.form.get("start", 0) or 0)
    length = float(request.form.get("length", 30) or 30)
    resolution = int(request.form.get("resolution", 1080) or 1080)
    output = request.form.get("output", "output.mp4").strip() or "output.mp4"
    use_embedded_image = request.form.get("use_embedded_image") == "on"
    
    # Handle file uploads
    audio_file_path = None
    image_file_path = None
    temp_files = []  # Track temp files for cleanup
    
    # Check for audio file upload
    audio_file = request.files.get("audio_file")
    if audio_file and audio_file.filename and allowed_audio_file(audio_file.filename):
        filename = secure_filename(audio_file.filename)
        temp_dir = tempfile.mkdtemp(prefix="video_gen_")
        audio_file_path = os.path.join(temp_dir, filename)
        audio_file.save(audio_file_path)
        temp_files.append(temp_dir)
    
    # Check for image file upload (only if not using embedded image)
    if not use_embedded_image:
        image_file = request.files.get("image_file")
        if image_file and image_file.filename and allowed_image_file(image_file.filename):
            filename = secure_filename(image_file.filename)
            if not temp_files:
                temp_dir = tempfile.mkdtemp(prefix="video_gen_")
                temp_files.append(temp_dir)
            else:
                temp_dir = temp_files[0]
            image_file_path = os.path.join(temp_dir, filename)
            image_file.save(image_file_path)
    
    # Validate inputs
    if not audio_file_path and not audio_url:
        return json.dumps({"error": "Please provide either an audio URL or upload an audio file."}), 400
    
    if not use_embedded_image and not image_file_path and not image_url:
        return json.dumps({"error": "Please provide an image URL, upload an image file, or check 'Use embedded image from audio file'."}), 400

    # Create a job ID and start background processing
    job_id = str(uuid.uuid4())
    job_status[job_id] = {
        "status": "processing",
        "progress": 0,
        "message": "Starting..."
    }
    
    # Start background thread
    thread = threading.Thread(
        target=run_video_generation,
        args=(job_id, audio_url, image_url, start, length, output, resolution,
              audio_file_path, image_file_path, use_embedded_image, temp_files)
    )
    thread.daemon = True
    thread.start()
    
    return json.dumps({"job_id": job_id})


@app.get("/download/<filename>")
def download(filename: str):
    # Look in the output directory
    path = Path("output") / filename
    if not path.exists():
        return f"File not found: {filename}", 404
    return send_file(path, as_attachment=False)


if __name__ == "__main__":
    # Use threaded=True to allow handling multiple requests while encoding might block.
    app.run(debug=True, threaded=True)
