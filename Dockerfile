FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
# yt-dlp needs a JS runtime to solve YouTube's player challenges.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "app.py"]
