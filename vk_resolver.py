# vk_resolver.py
import re
import json
import requests
from typing import List, Dict

VK_API_URL = "https://vk.com/api.php"
VK_API_VERSION = "5.199"

def call_vk_api(method: str, params: dict) -> dict:
    """Call VK API method directly without token (for public data)."""
    params['v'] = VK_API_VERSION
    # Some endpoints work without token for public playlists
    response = requests.get(VK_API_URL, params={'method': method, **params}, timeout=10)
    if response.status_code != 200:
        raise Exception(f"HTTP {response.status_code}")
    data = response.json()
    if 'error' in data:
        raise Exception(f"VK API Error {data['error']['error_code']}: {data['error']['error_msg']}")
    return data

def get_playlist_tracks(playlist_url: str) -> List[Dict]:
    print(f"[DEBUG] Parsing URL: {playlist_url}")

    # Extract IDs
    match = re.search(r'(?:music|audio)[/_]playlist[/](\d+)_(\d+)(?:_([A-Za-z0-9]+))?', playlist_url)
    if not match:
        digits = re.findall(r'\d+', playlist_url)
        if len(digits) < 2:
            raise ValueError(f"Could not parse playlist URL: {playlist_url}")
        owner_id = digits[0]
        playlist_id = digits[1]
        access_key = ''
    else:
        owner_id = match.group(1)
        playlist_id = match.group(2)
        access_key = match.group(3) if len(match.groups()) >= 3 and match.group(3) else ''

    print(f"[DEBUG] owner={owner_id}, playlist={playlist_id}, key={access_key}")

    # Step 1: Get playlist info (public)
    try:
        meta = call_vk_api('audio.getPlaylistById', {
            'playlist_id': playlist_id,
            'owner_id': owner_id,
            'access_key': access_key,
            'extra_fields': 'owner,duration'
        })
        if not meta.get('playlist'):
            raise Exception("Playlist not found or private")
        print(f"[DEBUG] Playlist title: {meta['playlist']['title']}")
    except Exception as e:
        print(f"[ERROR] Failed to get playlist info: {e}")
        # Fallback: try without access_key
        if access_key:
            try:
                meta = call_vk_api('audio.getPlaylistById', {
                    'playlist_id': playlist_id,
                    'owner_id': owner_id,
                    'extra_fields': 'owner,duration'
                })
                if meta.get('playlist'):
                    access_key = ''  # It worked without key
                    print("[DEBUG] Access key not needed")
            except:
                pass
        else:
            raise

    # Step 2: Get audio IDs from playlist source
    source_entity = f"{owner_id}_{playlist_id}{'_' + access_key if access_key else ''}"
    ids_data = call_vk_api('audio.getAudioIdsBySource', {
        'source': 'playlist',
        'entity_id': source_entity
    })
    audio_ids = ids_data.get('audios', [])
    if not audio_ids:
        raise Exception("No tracks found in playlist")

    print(f"[DEBUG] Found {len(audio_ids)} audio IDs")

    # Step 3: Fetch full track details in batches
    all_tracks = []
    chunk_size = 100
    for i in range(0, len(audio_ids), chunk_size):
        chunk = audio_ids[i:i+chunk_size]
        ids = ','.join(str(t.get('audio_id', t) if isinstance(t, dict) else t) for t in chunk)
        track_data = call_vk_api('audio.getById', {'audios': ids})
        if isinstance(track_data, list):
            for t in track_data:
                all_tracks.append({
                    'artist': t.get('artist', 'Unknown'),
                    'title': t.get('title', 'Unknown'),
                    'duration': t.get('duration', 0)
                })

    if not all_tracks:
        raise Exception("No track details retrieved")

    print(f"[DEBUG] Extracted {len(all_tracks)} tracks")
    return all_tracks