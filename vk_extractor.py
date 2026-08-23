# vk_extractor.py
import subprocess
import json
import os

def extract_playlist_with_puppeteer(playlist_url: str) -> dict:
    """Call the Node.js puppeteer script and return the result."""
    script_path = os.path.join(os.path.dirname(__file__), 'extract.js')
    try:
        result = subprocess.run(
            ['node', script_path, playlist_url],
            capture_output=True,
            text=True,
            timeout=60,
            check=True
        )
        # The script outputs JSON on stdout
        output = result.stdout.strip()
        if not output:
            raise Exception("No output from puppeteer script")
        data = json.loads(output)
        if 'error' in data:
            raise Exception(data['error'])
        return data
    except subprocess.TimeoutExpired:
        raise Exception("Puppeteer timed out after 60 seconds")
    except subprocess.CalledProcessError as e:
        raise Exception(f"Puppeteer error: {e.stderr}")
    except json.JSONDecodeError:
        raise Exception(f"Invalid JSON from puppeteer: {output}")