import os
import re
import json
import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import yt_dlp
import httpx

app = FastAPI(title="BelFetch Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

port = int(os.getenv("PORT", "8000"))


class ExtractRequest(BaseModel):
    url: str


class QualityOption(BaseModel):
    id: str
    label: str
    resolution: str
    sizeBytes: int
    downloadUrl: Optional[str] = None


class ExtractResponse(BaseModel):
    url: str
    title: str
    creator: Optional[str] = None
    duration: Optional[int] = None
    thumbnailUrl: Optional[str] = None
    qualities: list[QualityOption]
    fetchedAt: str


def _format_filesize(size) -> int:
    if size is None:
        return 0
    try:
        return int(size)
    except (ValueError, TypeError):
        return 0


def _parse_duration(seconds) -> Optional[int]:
    if seconds is None:
        return None
    try:
        return int(float(seconds))
    except (ValueError, TypeError):
        return None


def _extract_direct_formats(info: dict) -> list[dict]:
    formats = info.get("formats", [])
    direct = []
    for f in formats:
        url = f.get("url")
        if not url:
            continue
        protocol = f.get("protocol", "")
        if protocol in ("http", "https", "m3u8_native", "mhtml", "m3u8"):
            direct.append(f)

    direct.sort(
        key=lambda f: (
            _format_filesize(f.get("filesize") or f.get("filesize_approx")),
            f.get("height") or 0,
        ),
        reverse=True,
    )
    return direct


def _pick_best_direct_url(formats: list[dict]) -> Optional[str]:
    mp4_video = next(
        (
            f
            for f in formats
            if f.get("ext") == "mp4"
            and f.get("vcodec") != "none"
            and f.get("acodec") == "none"
        ),
        None,
    )
    mp4_audio = next(
        (
            f
            for f in formats
            if f.get("ext") == "mp4"
            and f.get("acodec") != "none"
            and f.get("vcodec") == "none"
        ),
        None,
    )
    if mp4_video and mp4_audio:
        return mp4_video.get("url")

    mp4_progressive = next(
        (
            f
            for f in formats
            if f.get("ext") == "mp4"
            and f.get("vcodec") != "none"
            and f.get("acodec") != "none"
        ),
        None,
    )
    if mp4_progressive:
        return mp4_progressive.get("url")

    any_progressive = next(
        (
            f
            for f in formats
            if f.get("vcodec") != "none" and f.get("acodec") != "none"
        ),
        None,
    )
    if any_progressive:
        return any_progressive.get("url")

    if formats:
        return formats[0].get("url")

    return None


def _build_qualities(
    direct_formats: list[dict],
    fallback_url: Optional[str],
) -> list[dict]:
    qualities = []
    seen_urls = set()
    seen_labels = set()
    best_url = _pick_best_direct_url(direct_formats)

    if best_url:
        seen_urls.add(best_url)

    def add_quality(label: str, resolution: str, url: Optional[str], size: int):
        if url and url in seen_urls:
            return
        if url:
            seen_urls.add(url)
        key = f"{label}|{resolution}"
        if key in seen_labels:
            return
        seen_labels.add(key)
        qualities.append(
            {
                "id": re.sub(r"[^a-zA-Z0-9_-]", "_", f"{label}_{resolution}").lower(),
                "label": label,
                "resolution": resolution,
                "sizeBytes": size,
                "downloadUrl": url or fallback_url,
            }
        )

    seen_res_heights = set()
    for f in direct_formats:
        height = f.get("height")
        if not height or height in seen_res_heights:
            continue
        seen_res_heights.add(height)

        size = _format_filesize(f.get("filesize") or f.get("filesize_approx"))
        label = f"{height}p"
        resolution = f"{height}p"
        add_quality(label, resolution, f.get("url"), size)

    add_quality("Best", "best", best_url or fallback_url, 0)

    return qualities


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestvideo+bestaudio/best",
        "noplaylist": True,
    }

    cookie_file = os.getenv("COOKIE_FILE")
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    cookie_browser = os.getenv("COOKIES_FROM_BROWSER")
    if cookie_browser:
        ydl_opts["cookiesfrombrowser"] = (cookie_browser,)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract: {str(e)}")

    if info is None:
        raise HTTPException(status_code=400, detail="No metadata found for URL")

    title = info.get("title") or "Untitled"
    creator = info.get("uploader") or info.get("channel") or info.get("creator")
    duration = _parse_duration(info.get("duration"))

    thumbnails = info.get("thumbnails") or []
    thumbnail = None
    if thumbnails:
        thumbnail = thumbnails[-1].get("url") or thumbnails[0].get("url")
    if not thumbnail:
        thumbnail = info.get("thumbnail")

    direct_formats = _extract_direct_formats(info)
    qualities = _build_qualities(direct_formats, url)

    return ExtractResponse(
        url=url,
        title=title,
        creator=creator,
        duration=duration,
        thumbnailUrl=thumbnail,
        qualities=[QualityOption(**q) for q in qualities],
        fetchedAt=datetime.datetime.now().isoformat(),
    )


@app.get("/download")
async def download_proxy(url: str = Query(...)):
    if not url:
        raise HTTPException(status_code=400, detail="url query param is required")

    filename = "video.mp4"
    try:
        parsed = url.split("?")[0].split("/")[-1]
        if "." in parsed:
            filename = parsed
    except Exception:
        pass

    async def generate():
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                    yield chunk

    return StreamingResponse(
        generate(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=port)
