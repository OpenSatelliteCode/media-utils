import os
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import yt_dlp

app = FastAPI(title="media-utils")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

DOWNLOAD_DIR = Path("/tmp/media-utils")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def cleanup_old_files(max_files: int = 20):
    """Evita que se acumule basura en /tmp si Railway no reinicia seguido."""
    files = sorted(DOWNLOAD_DIR.glob("*"), key=os.path.getmtime)
    if len(files) > max_files:
        for f in files[: len(files) - max_files]:
            try:
                f.unlink()
            except Exception:
                pass


@app.get("/", response_class=HTMLResponse)
def root():
    index_path = Path(__file__).parent / "static" / "index.html"
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return "<h1>media-utils backend corriendo. Falta static/index.html</h1>"


@app.get("/api/info")
def get_info(url: str = Query(..., description="URL del video/audio")):
    """Regresa info del link (título, formatos disponibles, duración, etc.) sin descargar."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"No pude leer el link: {e}")

    formats = []
    for f in info.get("formats", []):
        if f.get("vcodec") == "none" and f.get("acodec") == "none":
            continue
        formats.append(
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution") or f.get("format_note"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "note": f.get("format_note"),
            }
        )

    return {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "extractor": info.get("extractor"),
        "formats": formats,
    }


@app.get("/api/download")
def download(
    url: str = Query(...),
    mode: str = Query("video", regex="^(video|video_only|audio)$"),
    format_id: str | None = Query(None, description="format_id específico de /api/info"),
):
    """Descarga el video/audio y lo regresa como archivo.

    mode:
      - video: video + audio mezclados (mp4)
      - video_only: solo el video, sin pista de audio (mp4)
      - audio: solo audio, convertido a mp3
    """
    file_id = uuid.uuid4().hex
    outtmpl = str(DOWNLOAD_DIR / f"{file_id}.%(ext)s")

    if mode == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
    elif mode == "video_only":
        fmt = format_id if format_id else "bestvideo/best"
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            # nos aseguramos de no arrastrar audio por accidente
            "postprocessor_args": {"ffmpeg": ["-an"]},
        }
    else:
        fmt = format_id if format_id else "bestvideo+bestaudio/best"
        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if mode == "audio":
                filename = str(Path(filename).with_suffix(".mp3"))
            elif mode in ("video", "video_only") and not filename.endswith(".mp4"):
                possible = str(Path(filename).with_suffix(".mp4"))
                if Path(possible).exists():
                    filename = possible
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Falló la descarga: {e}")

    if not Path(filename).exists():
        raise HTTPException(status_code=500, detail="El archivo no se generó correctamente.")

    cleanup_old_files()

    title = info.get("title", "download")
    safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:80]
    ext = Path(filename).suffix
    download_name = f"{safe_title}{ext}" if safe_title else f"download{ext}"

    return FileResponse(filename, filename=download_name, media_type="application/octet-stream")


static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
