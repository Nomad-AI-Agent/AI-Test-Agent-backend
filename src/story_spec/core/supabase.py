import os
from io import BytesIO
from typing import Optional
from supabase import create_client, Client
from story_spec.core import config

_client: Optional[Client] = None

def get_supabase() -> Optional[Client]:
    global _client
    if _client is None:
        if config.SUPABASE_URL and config.SUPABASE_KEY:
            _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client

def upload_screenshot(run_id: str, filename: str, image_data: bytes) -> Optional[str]:
    """Uploads a screenshot to Supabase and returns the public URL."""
    client = get_supabase()
    if not client:
        return None

    path = f"{run_id}/{filename}"

    try:
        # Upload file (upsert=True to avoid errors if retrying)
        client.storage.from_(config.SUPABASE_BUCKET).upload(
            path=path,
            file=image_data,
            file_options={"content-type": "image/png", "upsert": "true"}
        )

        res = client.storage.from_(config.SUPABASE_BUCKET).create_signed_url(path, expires_in=86400)

        url = res
        if isinstance(res, dict):
            url = res.get("signedUrl") or res.get("signed_url")

        print(f"Supabase upload success: {url}")
        return url
    except Exception as e:
        print(f"Supabase upload error: {e}")
        return None


def download_screenshot(run_id: str, filename: str) -> Optional[bytes]:
    """Downloads a screenshot from Supabase storage."""
    client = get_supabase()
    if not client:
        return None

    path = f"{run_id}/{filename}"

    try:
        res = client.storage.from_(config.SUPABASE_BUCKET).download(path)
        return res
    except Exception as e:
        print(f"Supabase download error: {e}")
        return None
