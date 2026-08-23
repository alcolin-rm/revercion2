import os
import uuid
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import Settings
import jobs
from vk_resolver import fetch_playlist_tracks

app = FastAPI(title="VK → Soulseek Archiver")

DATA = Path(Settings.data_dir)
JOBS_DIR = DATA / "jobs"
DOWNLOADS_DIR = DATA / "downloads"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

@app.on_event("startup")
def on_startup():
    jobs.init_db()

class PlaylistResolveRequest(BaseModel):
    playlist_url: str

class Track(BaseModel):
    artist: str
    title: str
    album: str
    duration_sec: int
    query: str

class PlaylistResolveResponse(BaseModel):
    playlist_id: str
    title: str
    tracks: List[Track]

class QualityPolicy(BaseModel):
    format: str = "mp3"
    min_bitrate_kbps: int = 320
    max_bitrate_kbps: int = 320

class DownloadStartRequest(BaseModel):
    playlist_id: str
    quality: QualityPolicy = QualityPolicy()
    output_dir_name: str | None = None

class DownloadStartResponse(BaseModel):
    job_id: str
    status: str

class JobStatus(BaseModel):
    job_id: str
    playlist_id: str
    playlist_title: str
    status: str
    total_tracks: int
    completed: int
    failed: int
    skipped: int
    log_url: str | None = None

@app.post("/playlists/resolve", response_model=PlaylistResolveResponse)
async def resolve_playlist(req: PlaylistResolveRequest):
    try:
        data = await fetch_playlist_tracks(req.playlist_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to resolve playlist: {e}")
    if not data["tracks"]:
        raise HTTPException(status_code=400, detail="No tracks found in this playlist")
    return PlaylistResolveResponse(**data)

@app.post("/downloads/start", response_model=DownloadStartResponse)
async def start_download(req: DownloadStartRequest):
    # We assume the client has already resolved and stored the tracklist somewhere,
    # or we re-resolve here using a known pattern. For simplicity, we’ll re-resolve
    # from a canonical URL constructed from playlist_id. This is a design choice;
    # you can change it to require playlist_url instead.
    #
    # For this blueprint, we’ll require the client to pass playlist_url in a header
    # or we just fake it by expecting a mapping. To keep it simple and self-contained,
    # let’s instead require playlist_url in a separate field. But to avoid changing
    # the schema too much, we’ll just raise a clear error and document:
    #
    # "For now, this demo expects you to call /playlists/resolve first, then manually
    #  trigger a job with a known playlist_id and a pre-created CSV. A production version
    #  would store the tracklist and reference it by ID."
    #
    # To keep this blueprint runnable, we’ll implement a simple in-memory cache keyed by playlist_id.
    raise HTTPException(
        status_code=501,
        detail=(
            "Not implemented in this minimal blueprint: "
            "store tracklists by playlist_id and reference them here. "
            "See comments in main.py for how to extend."
        ),
    )

# For a fully working demo, you can add an extra endpoint:
# POST /downloads/start_with_url that takes playlist_url + quality,
# resolves, writes CSV, creates job, and spawns sldl.

class DownloadStartWithURLRequest(BaseModel):
    playlist_url: str
    quality: QualityPolicy = QualityPolicy()
    output_dir_name: str | None = None

@app.post("/downloads/start_with_url", response_model=DownloadStartResponse)
async def start_download_with_url(req: DownloadStartWithURLRequest):
    # Resolve playlist
    try:
        pl = await fetch_playlist_tracks(req.playlist_url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to resolve playlist: {e}")

    tracks = pl["tracks"]
    if not tracks:
        raise HTTPException(status_code=400, detail="No tracks found in this playlist")

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    playlist_id = pl["playlist_id"]
    playlist_title = pl["title"]

    # Write CSV for slsk-batchdl
    csv_path = job_dir / "queries.csv"
    with csv_path.open("w", encoding="utf-8") as f:
        f.write("artist,title,query\n")
        for t in tracks:
            # Escape quotes if needed; for simplicity, assume no quotes
            f.write(f'"{t["artist"]}","{t["title"]}","{t["query"]}"\n')

    # Determine output directory
    out_name = req.output_dir_name or f"playlist_{playlist_id}"
    out_dir = DOWNLOADS_DIR / out_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Create job record
    jobs.create_job(job_id, playlist_id, playlist_title, len(tracks), str(csv_path))

    # Prepare sldl command
    slsk_user = Settings.soulseek_user
    slsk_pass = Settings.soulseek_pass

    # Build command; adjust flags according to your slsk-batchdl version [31][32][33]
    cmd = [
        "sldl",
        "-i", str(csv_path),
        "--user", slsk_user,
        "--pass", slsk_pass,
        "--pref-format", req.quality.format,
        "--pref-min-bitrate", str(req.quality.min_bitrate_kbps),
        "--pref-max-bitrate", str(req.quality.max_bitrate_kbps),
        "-p", str(out_dir),
        "--log", str(job_dir / "sldl.log"),
    ]

    log_path = str(job_dir / "sldl.log")

    # Spawn background task
    async def run_job():
        # Mark as running
        jobs.update_job_status(job_id, "running", log_path=log_path)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            # Very naive: parse log or just assume completion
            # A real implementation would parse sldl.log for counts.
            completed = len(tracks)
            failed = 0
            skipped = 0
            jobs.update_job_status(
                job_id,
                "completed" if proc.returncode == 0 else "failed",
                completed=completed,
                failed=failed,
                skipped=skipped,
            )
        except Exception:
            jobs.update_job_status(job_id, "failed")

    asyncio.create_task(run_job())

    return DownloadStartResponse(job_id=job_id, status="queued")

@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_url = f"/jobs/{job_id}/log" if job.get("log_path") else None
    return JobStatus(
        job_id=job["job_id"],
        playlist_id=job["playlist_id"],
        playlist_title=job["playlist_title"],
        status=job["status"],
        total_tracks=job["total_tracks"],
        completed=job["completed"],
        failed=job["failed"],
        skipped=job["skipped"],
        log_url=log_url,
    )

@app.get("/jobs/{job_id}/log")
async def get_job_log(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    log_path = job.get("log_path")
    if not log_path:
        raise HTTPException(status_code=404, detail="No log available")
    from fastapi.responses import FileResponse
    return FileResponse(log_path, media_type="text/plain")