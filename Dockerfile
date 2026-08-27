FROM python:3.11-slim

# ffmpeg         – audio pipeline (loudnorm, mono/stereo, MP3)
# Node.js 22     – JavaScript runtime required by yt-dlp >= 2026 to solve
#                  YouTube's n-challenge (EJS). Debian's built-in nodejs is
#                  only v18 which yt-dlp rejects (minimum: v22).
#                  We install from the official NodeSource repo instead.
# ca-certificates – needed for HTTPS downloads and the NodeSource setup script
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates ffmpeg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Berlin \
    PORT=8080

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# spotdl pulls fastapi<0.104 + uvicorn<0.24 (for its own optional web-UI,
# which we never use) plus a long chain of real runtime deps it needs even
# for plain library use (rapidfuzz, platformdirs, pykakasi, datastar-py,
# syncedlyrics, spotipy, ytmusicapi, ...). Installing spotdl with --no-deps
# and manually re-listing "the handful of deps it needs" is fragile: every
# spotdl release can add new imports, and any dep missed here breaks Spotify
# downloads at runtime with ModuleNotFoundError (this happened with
# rapidfuzz in 4.5.2). Instead: install spotdl WITH its full dependency
# tree, then re-pin the packages it tries to downgrade back to the versions
# our own app needs (fastapi/starlette/anyio/uvicorn).
RUN pip install --no-cache-dir spotdl \
    && pip install --no-cache-dir \
        "fastapi>=0.110" "starlette>=1.0.0" "anyio>=4.0,<5" "uvicorn[standard]>=0.27"

COPY app ./app
COPY templates ./templates
COPY static ./static

# Data volumes are mounted at /data/audio and /data/db (see docker-compose.yml).
VOLUME ["/data/audio", "/data/db"]

EXPOSE 8080

# yt-dlp is upgraded automatically on startup (see app/main.py).
CMD ["python", "-m", "app.main"]
