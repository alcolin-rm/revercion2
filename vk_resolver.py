# vk_resolver.py
import re
import json
import requests
from typing import List, Dict

def get_playlist_tracks(playlist_url: str) -> List[Dict]:
    """
    Extract tracks from a public VK playlist using VK's widget API.
    Returns a list of dicts with keys: artist, title, duration.
    Returns empty list if no tracks found or playlist is private.
    """
    print(f"[DEBUG] Parsing URL: {playlist_url}")

    # Try several regex patterns to extract owner_id, playlist_id, and access_key
    patterns = [
        # Format: music/playlist/123_456_abc
        r'(?:music|audio)[/_]playlist[/](\d+)_(\d+)(?:_([A-Za-z0-9]+))?',
        # Format: audio_playlist/123_456
        r'(?:audio|music)[/_]playlist[/](\d+)_(\d+)(?:_([A-Za-z0-9]+))?',
        # Fallback: any digits_underscore_digits_underscore_alnum
        r'(\d+)_(\d+)(?:_([A-Za-z0-9]+))?'
    ]

    match = None
    for pattern in patterns:
        match = re.search(pattern, playlist_url)
        if match:
            break

    if not match:
        raise ValueError(f"Could not parse playlist URL: {playlist_url}")

    owner_id = match.group(1)
    playlist_id = match.group(2)
    access_key = match.group(3) if len(match.groups()) >= 3 else ''

    print(f"[DEBUG] Extracted: owner={owner_id}, playlist={playlist_id}, key={access_key}")

    # Build the widget API URL
    widget_url = f"https://vk.com/widget_audio.php?act=load_playlist&owner_id={owner_id}&playlist_id={playlist_id}"
    if access_key:
        widget_url += f"&access_key={access_key}"

    try:
        response = requests.get(widget_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            print(f"[ERROR] HTTP {response.status_code}")
            return []  # Return empty list instead of raising

        json_match = re.search(r'\{.*\}', response.text)
        if not json_match:
            print("[ERROR] No JSON data in response")
            return []

        data = json.loads(json_match.group(0))
        playlist_data = data.get('playlist')
        if not playlist_data:
            print("[ERROR] No 'playlist' key in data")
            return []

        tracks = playlist_data.get('audios')
        if not tracks or not isinstance(tracks, list):
            print("[ERROR] No 'audios' list in playlist data")
            return []

        return [{
            'artist': t.get('artist', 'Unknown'),
            'title': t.get('title', 'Unknown'),
            'duration': t.get('duration', 0)
        } for t in tracks]

    except Exception as e:
        print(f"[ERROR] Exception in get_playlist_tracks: {e}")
        return []  # Return empty list on any error