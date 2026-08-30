FROM python:3.12-slim

LABEL maintainer="ywsj"
LABEL description="ywsj Video Downloader - Web UI for yt-dlp with Cloudflare bypass and auth"

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    flask \
    gunicorn \
    yt-dlp \
    curl_cffi

# App directory
WORKDIR /app

COPY . .

# Download + data directories
RUN mkdir -p /app/downloads /app/data

VOLUME /app/downloads
VOLUME /app/data

EXPOSE 5200

# Default auth (override with env vars)
ENV AUTH_USERNAME=admin
ENV AUTH_PASSWORD=admin123

# Single worker + multiple threads: tasks dict lives in-process memory,
# must be shared across all requests (download threads + polling)
CMD ["gunicorn", "--bind", "0.0.0.0:5200", "--workers", "1", "--threads", "8", "--timeout", "600", "app:app"]
