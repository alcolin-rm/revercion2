# vk_resolver.py
import re
import json
import requests
from typing import List, Dict
from urllib.parse import urlparse

def get_playlist_tracks(playlist_url: str) -> List[Dict]:
    print(f"[DEBUG] vk_resolver received URL: {playlist_url}")

    # Method 1: Extract using regex that looks for digits and optional alphanumeric key
    # This handles:
    #   /music/playlist/123_456_abc
    #   /audio_playlist/123_456
    #   /123_456_abc (just the ID part)
    match = re.search(r'(?:music|audio)[/_]playlist[/](\d+)_(\d+)(?:_([a-f0-9]+))?', playlist_url)
    if not match:
        # Fallback: just extract all digits and take first two
        digits = re.findall(r'\d+', playlist_url)
        if len(digits) >= 2:
            owner_id, playlist_id = digits[0], digits[1]
            # Try to find access key after the second underscore
            key_match = re.search(r'_\d+_([A-Za-z0-9]+)', playlist_url)
            access_key = key_match.group(1) if key_match else ''
            print(f"[DEBUG] Fallback extracted: owner={owner_id}, playlist={playlist_id}, key={access_key}")
        else:
            raise ValueError(f"Could not parse playlist URL: {playlist_url}")
    else:
        owner_id = match.group(1)
        playlist_id = match.group(2)
        access_key = match.group(3) if len(match.groups()) >= 3 and match.group(3) else ''
        print(f"[DEBUG] Regex extracted: owner={owner_id}, playlist={playlist_id}, key={access_key}")

    # Build the widget API URL
    widget_url = f"https://vk.com/widget_audio.php?act=load_playlist&owner_id={owner_id}&playlist_id={playlist_id}"
    if access_key:
        widget_url += f"&access_key={access_key}"
    print(f"[DEBUG] Widget URL: {widget_url}")

    try:
        response = requests.get(widget_url, timeout=10, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            print(f"[ERROR] HTTP {response.status_code}")
            return []  # Return empty list on HTTP error

        json_match = re.search(r'\{.*\}', response.text)
        if not json_match:
            print("[ERROR] No JSON data in response")
            return []

        data = json.loads(json_match.group(0))
        tracks = data.get('playlist', {}).get('audios', [])
        if not tracks:
            print("[ERROR] No tracks found in playlist data")
            return []

        return [{
            'artist': t.get('artist', 'Unknown'),
            'title': t.get('title', 'Unknown'),
            'duration': t.get('duration', 0)
        } for t in tracks]

    except Exception as e:
        print(f"[ERROR] Exception in get_playlist_tracks: {e}")
        return []  # Return empty list on any error