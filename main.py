# main.py
import asyncio
import json
import hashlib
import random
import socket
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
import requests

from config import settings
from jobs import DB_PATH

# ──────────────────────────────────────────────────────────────
# Soulseek imports
# ──────────────────────────────────────────────────────────────
try:
    from aioslsk.client import SoulSeekClient
    from aioslsk.settings import Settings as SlskSettings, CredentialsSettings
    SLSK_AVAILABLE = True
except ImportError:
    SLSK_AVAILABLE = False
    print("⚠️ aioslsk not installed – Soulseek download disabled")

# ──────────────────────────────────────────────────────────────
# VK Resolver – with detailed error handling
# ──────────────────────────────────────────────────────────────
VK_RESOLVER_AVAILABLE = False
try:
    from vk_resolver import get_playlist_tracks
    VK_RESOLVER_AVAILABLE = True
    print("✅ vk_resolver.py loaded successfully")
except Exception as e:
    print(f"⚠️ vk_resolver.py import failed: {e}")
    # define a fallback function
    def get_playlist_tracks(url):
        raise NotImplementedError("vk_resolver not available – using fallback")

# ──────────────────────────────────────────────────────────────
# FastAPI App
# ──────────────────────────────────────────────────────────────
app = FastAPI(title="Revercion2 – VK Playlist Downloader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static & templates
STATIC_PATH = Path(settings.data_dir) / "static"
STATIC_PATH.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_PATH)), name="static")

# If you have a templates folder, you can use Jinja2, but we'll serve HTML directly

# ──────────────────────────────────────────────────────────────
# Global State
# ──────────────────────────────────────────────────────────────
download_history: List[Dict] = []
jobs: Dict[str, Dict] = {}

# ──────────────────────────────────────────────────────────────
# Soulseek Manager (same as before)
# ──────────────────────────────────────────────────────────────
class SoulseekManager:
    def __init__(self):
        self.client = None
        self.is_connected = False

    async def initialize(self):
        if not SLSK_AVAILABLE:
            return False
        try:
            slsk_settings = SlskSettings(
                credentials=CredentialsSettings(
                    username=settings.soulseek_user,
                    password=settings.soulseek_pass or ""
                )
            )
            self.client = SoulSeekClient(slsk_settings)
            await self.client.start()
            await self.client.login()
            self.is_connected = True
            print(f"[Soulseek] ✅ Connected as {settings.soulseek_user}")
            return True
        except Exception as e:
            print(f"[Soulseek] ❌ Connection failed: {e}")
            self.is_connected = False
            return False

    async def search_track(self, artist: str, title: str, quality: str = "320") -> Optional[Dict]:
        if not self.client or not self.is_connected:
            await self.initialize()
            if not self.is_connected:
                return None

        query = f"{artist} {title}"
        print(f"[Search] {query}")

        try:
            if hasattr(self.client, 'search'):
                search_result = await self.client.search(query)
                if not search_result:
                    return None
                results = search_result.results if hasattr(search_result, 'results') else []
                if not results:
                    return None

                best_match = None
                best_score = -1

                for result in results:
                    files = result.files if hasattr(result, 'files') else []
                    users = result.users if hasattr(result, 'users') else []

                    for file in files:
                        if quality.isdigit():
                            target_kbps = int(quality)
                            if file.bitrate and file.bitrate < target_kbps:
                                continue
                        elif quality == "lossless":
                            lossless_exts = {'.flac', '.wav', '.aiff'}
                            if not any(file.filename.lower().endswith(ext) for ext in lossless_exts):
                                continue

                        score = len(users) * 10
                        if file.bitrate:
                            score += file.bitrate / 32

                        if score > best_score:
                            best_score = score
                            best_match = {
                                "filename": file.filename,
                                "size": file.size,
                                "bitrate": file.bitrate,
                                "users": [u.username for u in users] if users else [],
                                "filepath": file.path,
                                "artist": artist,
                                "title": title,
                                "username": users[0].username if users else None
                            }

                return best_match
            return None
        except Exception as e:
            print(f"[Search Error] {query}: {e}")
            return None

    async def download_file(self, file_info: Dict, target_path: Path) -> bool:
        try:
            username = file_info.get('username')
            if not username:
                users = file_info.get('users', [])
                if not users:
                    return False
                username = users[0]

            if hasattr(self.client, 'download'):
                await self.client.download(
                    username=username,
                    path=file_info['filepath'],
                    size=file_info['size'],
                    destination=str(target_path)
                )
                if target_path.exists() and target_path.stat().st_size > 0:
                    print(f"[Downloaded] {target_path.name}")
                    return True
            return False
        except Exception as e:
            print(f"[Download Error] {e}")
            return False

slsk_mgr = SoulseekManager()

# ──────────────────────────────────────────────────────────────
# VK Playlist Extractor (Fallback)
# ──────────────────────────────────────────────────────────────
def extract_vk_playlist_no_auth(playlist_url: str) -> List[Dict]:
    """
    Extract tracks from a public VK playlist using VK's widget API.
    This does NOT require any token or authentication.
    """
    # If vk_resolver is available and working, use it
    if VK_RESOLVER_AVAILABLE:
        try:
            tracks = get_playlist_tracks(playlist_url)
            if tracks:  # non-empty
                return tracks
        except Exception as e:
            print(f"vk_resolver failed: {e}, falling back to widget API")


    # Fallback: direct widget API
    match = re.search(r'(?:music|audio)[/_]playlist[/](\d+)_(\d+)(?:_([a-f0-9]+))?', playlist_url)
    if not match:
        raise ValueError("Could not parse playlist URL")

    owner_id = match.group(1)
    playlist_id = match.group(2)
    access_key = match.group(3) or ''

    widget_url = f"https://vk.com/widget_audio.php?act=load_playlist&owner_id={owner_id}&playlist_id={playlist_id}"
    if access_key:
        widget_url += f"&access_key={access_key}"

    try:
        response = requests.get(widget_url, timeout=settings.vk_timeout_sec, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code == 200:
            json_match = re.search(r'\{.*\}', response.text)
            if json_match:
                data = json.loads(json_match.group(0))
                tracks = data.get('playlist', {}).get('audios', [])
                if tracks:
                    return [{
                        'artist': t.get('artist', 'Unknown'),
                        'title': t.get('title', 'Unknown'),
                        'duration': t.get('duration', 0)
                    } for t in tracks]
    except Exception as e:
        print(f"Widget API failed: {e}")

    # Fallback: al_audio.php
    try:
        form_data = {
            'al': '1',
            'owner_id': owner_id,
            'playlist_id': playlist_id,
            'type': 'playlist'
        }
        if access_key:
            form_data['access_key'] = access_key

        response = requests.post(
            'https://vk.com/al_audio.php?act=load_section',
            data=form_data,
            timeout=settings.vk_timeout_sec,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'X-Requested-With': 'XMLHttpRequest'
            }
        )
        if response.status_code == 200:
            json_match = re.search(r'\{.*\}', response.text)
            if json_match:
                data = json.loads(json_match.group(0))
                tracks = data.get('playlist', {}).get('audios', [])
                if tracks:
                    return [{
                        'artist': t.get('artist', 'Unknown'),
                        'title': t.get('title', 'Unknown'),
                        'duration': t.get('duration', 0)
                    } for t in tracks]
    except Exception as e:
        print(f"al_audio.php failed: {e}")

    raise ValueError("Could not fetch playlist. It might be private or VK's API has changed.")

# ──────────────────────────────────────────────────────────────
# Download Manager (same as before)
# ──────────────────────────────────────────────────────────────
class DownloadManager:
    def __init__(self):
        self.slsk = slsk_mgr

    async def download_playlist(self, job_id: str, tracks: List[Dict], quality: str):
        try:
            self.update_job(job_id, status="searching", message="Connecting to Soulseek...")
            await self.slsk.initialize()
            if not self.slsk.is_connected:
                self.update_job(job_id, status="error", message="Soulseek connection failed. Enable VPN!")
                return

            total = len(tracks)
            downloaded = 0
            failed = 0
            dl_path = Path(settings.downloads_dir)

            for idx, track in enumerate(tracks, 1):
                if jobs.get(job_id, {}).get("status") == "cancelled":
                    self.update_job(job_id, status="cancelled", message="Cancelled by user")
                    return

                self.update_job(
                    job_id,
                    status="downloading",
                    message=f"Processing {idx}/{total}: {track['artist']} - {track['title']}",
                    progress=idx/total
                )

                safe_filename = re.sub(r'[<>:"/\\|?*]', '_', f"{track['artist']} - {track['title']}.mp3")
                target_path = dl_path / safe_filename

                if target_path.exists() and target_path.stat().st_size > 1024 * 1024:
                    downloaded += 1
                    continue

                file_info = await self.slsk.search_track(track['artist'], track['title'], quality)
                if not file_info:
                    failed += 1
                    continue

                success = await self.slsk.download_file(file_info, target_path)
                if success:
                    downloaded += 1
                    download_history.append({
                        "timestamp": datetime.now().isoformat(),
                        "artist": track['artist'],
                        "title": track['title'],
                        "bitrate": file_info.get('bitrate', 0),
                        "size": file_info.get('size', 0),
                        "path": str(target_path)
                    })
                    self._save_history()
                else:
                    failed += 1

            self.update_job(
                job_id,
                status="complete",
                message=f"Done! Downloaded: {downloaded}, Failed: {failed}, Total: {total}",
                progress=1.0,
                result={"downloaded": downloaded, "failed": failed, "total": total}
            )

        except Exception as e:
            self.update_job(job_id, status="error", message=str(e))
            print(f"[Job Error] {job_id}: {e}")

    def update_job(self, job_id: str, **kwargs):
        if job_id not in jobs:
            jobs[job_id] = {}
        jobs[job_id].update(kwargs)

    def _save_history(self):
        try:
            history_path = Path(settings.data_dir) / "history.json"
            history_path.parent.mkdir(exist_ok=True)
            with open(history_path, 'w', encoding='utf-8') as f:
                json.dump(download_history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[History Save Error] {e}")

dm = DownloadManager()

# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    # Serve the interactive HTML page
    html_path = Path("index.html")
    if html_path.exists():
        with open(html_path, 'r', encoding='utf-8') as f:
            return HTMLResponse(content=f.read())
    else:
        return HTMLResponse("""
        <h1>Revercion2 – VK Playlist Downloader</h1>
        <p>Please create an <code>index.html</code> file in the project root.</p>
        <p>API endpoints are available at <code>/api/...</code></p>
        """)

@app.post("/api/fetch-playlist")
async def fetch_playlist(playlist_url: str = Form(...)):
    print(f"[API] Received URL: '{playlist_url}'")  # <-- ADD THIS
    try:
        tracks = extract_vk_playlist_no_auth(playlist_url)
        return JSONResponse({
            "success": True,
            "tracks": tracks,
            "total": len(tracks)
        })
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=400)

@app.post("/api/download-playlist")
async def download_playlist(
    background_tasks: BackgroundTasks,
    playlist_url: str = Form(...),
    quality: str = Form("320")
):
    try:
        tracks = extract_vk_playlist_no_auth(playlist_url)
        if not tracks:
            return JSONResponse({
                "success": False,
                "error": "No tracks found. The playlist might be private or empty."
            }, status_code=404)  # Use 404 instead of 400

        job_id = hashlib.md5(f"{playlist_url}_{datetime.now().isoformat()}".encode()).hexdigest()[:12]

        jobs[job_id] = {
            "id": job_id,
            "status": "starting",
            "quality": quality,
            "message": f"Processing {len(tracks)} tracks...",
            "progress": 0.0,
            "created": datetime.now().isoformat()
        }

        background_tasks.add_task(
            dm.download_playlist,
            job_id,
            tracks,
            quality
        )

        return JSONResponse({
            "success": True,
            "job_id": job_id,
            "tracks": len(tracks)
        })
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/jobs")
async def get_jobs():
    return JSONResponse({"jobs": jobs})

@app.get("/api/test/connection")
async def test_connection():
    result = {"soulseek": False, "vpn_required": True, "message": ""}
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        code = sock.connect_ex(("server.slsknet.org", 2242))
        if code == 0:
            result["soulseek"] = True
            result["vpn_required"] = False
            result["message"] = "✅ Connected"
        else:
            result["message"] = "❌ Enable VPN! Soulseek unreachable."
        sock.close()
    except Exception as e:
        result["message"] = f"❌ Error: {str(e)[:50]}"
    return JSONResponse(result)

@app.get("/downloads")
async def list_downloads():
    dl_path = Path(settings.downloads_dir)
    files = []
    for ext in ['*.mp3', '*.flac', '*.wav', '*.m4a']:
        for f in dl_path.glob(ext):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "url": f"/downloads/file/{f.name}"
            })
    return JSONResponse({"files": sorted(files, key=lambda x: x['name'])})

@app.get("/downloads/file/{filename}")
async def download_file(filename: str):
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    file_path = Path(settings.downloads_dir) / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path, filename=filename)

@app.get("/api/history")
async def get_history(limit: int = 50):
    return JSONResponse({"history": download_history[-limit:]})

@app.get("/api/download/{job_id}/cancel")
async def cancel_job(job_id: str):
    if job_id in jobs:
        jobs[job_id]["status"] = "cancelled"
        jobs[job_id]["message"] = "Cancelled by user"
        return JSONResponse({"status": "cancelled"})
    raise HTTPException(status_code=404, detail="Job not found")

@app.get("/api/test-vk-resolver")
async def test_vk_resolver():
    try:
        from vk_resolver import get_playlist_tracks
        return {"status": "ok", "message": "vk_resolver loaded"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ──────────────────────────────────────────────────────────────
# Startup / Shutdown
# ──────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    history_path = Path(settings.data_dir) / "history.json"
    if history_path.exists():
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                download_history.extend(json.load(f))
            print(f"[History] Loaded {len(download_history)} entries")
        except Exception as e:
            print(f"[History] Failed to load: {e}")

@app.on_event("shutdown")
async def shutdown():
    try:
        history_path = Path(settings.data_dir) / "history.json"
        history_path.parent.mkdir(exist_ok=True)
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(download_history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Shutdown] Failed to save history: {e}")

# ──────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*60)
    print("🎵 Revercion2 – VK Playlist Downloader")
    print("="*60)
    print("")
    print("📌 How it works:")
    print("  • Uses VK's public widget API (no auth required)")
    print("  • Works for PUBLIC playlists only")
    print("  • Downloads tracks via Soulseek")
    print(f"  • Data directory: {settings.data_dir}")
    print(f"  • Downloads directory: {settings.downloads_dir}")
    print("")
    print("✅ Server: http://127.0.0.1:8000")
    print("="*60 + "\n")

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info"
    )