# BelFetch Backend

FastAPI backend that wraps **yt-dlp** so the BelFetch Flutter app can extract video metadata and download URLs for YouTube, Facebook, TikTok, Instagram, Vimeo, Dailymotion, and more.

## Features

- `POST /extract` — fetch video metadata and direct download URLs
- `GET /download` — proxy downloads to bypass CORS / cookie issues
- CORS enabled for the Flutter app
- Prefers MP4 progressive streams; falls back to best available direct URL
- Extracts title, creator, duration, thumbnail, and multiple quality options
- Supports Facebook (including login/age-restricted videos via optional cookies)

## Requirements

- Python 3.10+
- `yt-dlp` (installed via pip)
- `ffmpeg` recommended for merging separate audio/video streams
- Windows / Linux / macOS

## Setup

1. Clone or copy this `server` folder.
2. Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows
```

3. Install dependencies:

```bash
pip install -r requirements.txt
yt-dlp --version
```

4. (Optional) Install ffmpeg if you want merged audio+video downloads:

- **Windows:** https://www.gyan.dev/ffmpeg/builds/
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

## Run locally

```bash
python main.py
```

Server starts at `http://localhost:8000`

Test it:

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://www.youtube.com/watch?v=dQw4w9WgXcQ\"}"
```

## Deploy

### Railway

```bash
railway init
railway up
```

Railway auto-detects FastAPI. Set env vars in Railway dashboard if needed:
- `CORS_ORIGINS` — comma-separated origins, e.g. `https://your-app.vercel.app`
- `COOKIE_FILE` — path to a Netscape-format `cookies.txt` (optional, for restricted Facebook/Instagram videos)
- `COOKIES_FROM_BROWSER` — browser name to import cookies from, e.g. `chrome`, `firefox`, `edge` (optional)

### Render

1. Create new Web Service
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add env var `CORS_ORIGINS` with your app domain

### Fly.io

```bash
fly launch
fly deploy
```

### VPS (Docker)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t belfetch-backend .
docker run -p 8000:8000 -e CORS_ORIGINS="*" belfetch-backend
```

## Endpoints

### POST /extract

Request:
```json
{ "url": "https://www.youtube.com/watch?v=..." }
```

Response:
```json
{
  "url": "https://www.youtube.com/watch?v=...",
  "title": "Video Title",
  "creator": "Channel Name",
  "duration": 240,
  "thumbnailUrl": "https://...",
  "qualities": [
    {
      "id": "1080p",
      "label": "1080p",
      "resolution": "1080p",
      "sizeBytes": 52428800,
      "downloadUrl": "https://..."
    }
  ],
  "fetchedAt": "2024-01-01T00:00:00"
}
```

### GET /download?url=<direct_stream_url>

Streams the video file through the backend. Use this when direct URLs have CORS blocks or signed URLs.

## Notes

- yt-dlp blocks change frequently. Update regularly: `pip install --upgrade yt-dlp`
- Some platforms may rate-limit or block the server IP. Consider a proxy or rotating IPs if needed.
- The backend intentionally does **not** store videos permanently. It extracts metadata and proxies streams on demand.
- For production, add rate limiting and auth if you don't want it public.
