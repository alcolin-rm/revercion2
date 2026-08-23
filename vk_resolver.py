import re
import httpx
from typing import List, Dict, Any, Optional
from config import settings

VK_AL_AUDIO = "https://vk.com/al_audio.php"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://vk.com/",
}

PLAYLIST_URL_RE = re.compile(
    r"vk\.com/audios?(?P<owner_id>-?\d+).*?"
    r"audio_playlist(?P<owner_id2>-?\d+)_(?P<playlist_id>\d+)"
)

def parse_playlist_url(url: str) -> tuple[str, str]:
    m = PLAYLIST_URL_RE.search(url)
    if not m:
        raise ValueError("Invalid VK playlist URL")
    if m.group("owner_id") != m.group("owner_id2"):
        raise ValueError("Owner ID mismatch in playlist URL")
    return m.group("owner_id"), m.group("playlist_id")

async def fetch_playlist_tracks(playlist_url: str) -> Dict[str, Any]:
    owner_id, playlist_id = parse_playlist_url(playlist_url)
    section_arg = f"playlist{owner_id}_{playlist_id}"

    async with httpx.AsyncClient(timeout=settings.vk_timeout_sec) as client:
        resp = await client.post(
            VK_AL_AUDIO,
            headers=HEADERS,
            data={
                "act": "load_section",
                "al": "1",
                "section": section_arg,
            },
        )
        resp.raise_for_status()

    # VK returns a JSON array; the last element usually contains the playlist data.
    # Exact structure can vary; we’ll be defensive.
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("Unexpected VK response format (not a list)")

    # Heuristic: find the part that contains 'playlist' or 'list' with tracks.
    # In many cases, data[-1] is a dict with 'playlist' or similar.
    payload = None
    for chunk in reversed(data):
        if isinstance(chunk, dict):
            if "playlist" in chunk or "list" in chunk or "audio" in chunk:
                payload = chunk
                break
    if payload is None:
        # Fallback: assume last element holds something useful
        payload = data[-1] if isinstance(data[-1], dict) else {}

    # Extract title
    title = payload.get("title", "") or payload.get("playlist", {}).get("title", "") or f"Playlist {owner_id}_{playlist_id}"

    # Extract tracks – structure differs; often under 'playlist' -> 'tracks' or 'list'
    raw_tracks = (
        payload.get("playlist", {}).get("tracks", [])
        or payload.get("list", [])
        or payload.get("audio", [])
        or []
    )

    tracks: List[Dict[str, Any]] = []
    for t in raw_tracks:
        if not isinstance(t, dict):
            continue
        artist = t.get("artist", "") or t.get("performer", "") or ""
        title_track = t.get("title", "") or t.get("track", "") or ""
        album = t.get("album", "") or ""
        duration = t.get("duration", 0) or t.get("duration_sec", 0) or 0

        if not artist and not title_track:
            continue

        query = f"{artist} - {title_track}".strip()
        tracks.append({
            "artist": artist,
            "title": title_track,
            "album": album,
            "duration_sec": int(duration),
            "query": query,
        })

    return {
        "playlist_id": f"{owner_id}_{playlist_id}",
        "title": title,
        "tracks": tracks,
    }