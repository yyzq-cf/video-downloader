FROM python:3.12-slim

LABEL maintainer="ywsj"
LABEL description="ywsj Video Downloader - Web UI for yt-dlp with Cloudflare bypass"

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

# Download directory
RUN mkdir -p /app/downloads

VOLUME /app/downloads

EXPOSE 5200

# Gunicorn with threaded workers
CMD ["gunicorn", "--bind", "0.0.0.0:5200", "--workers", "2", "--threads", "4", "--timeout", "600", "app:app"]
