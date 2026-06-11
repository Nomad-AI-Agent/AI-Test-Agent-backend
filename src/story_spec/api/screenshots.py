"""Screenshot handling and retrieval."""

import io
from typing import Optional
from urllib.parse import urlparse
from pathlib import Path

from fastapi import HTTPException

from story_spec.core import config, supabase


async def get_screenshot(run_id: str, filename: str) -> bytes:
    """
    Retrieve a screenshot by run_id and filename.
    
    First tries Supabase, then falls back to local file storage.
    
    Args:
        run_id: The run ID
        filename: The filename (can be a URL or just a filename)
    
    Returns:
        Image data as bytes
        
    Raises:
        HTTPException: If screenshot is not found
    """
    # If the filename is a full URL, extract just the filename from the path
    if filename.startswith("http"):
        # Extract filename from URL path (e.g., .../step_00.png?token=... -> step_00.png)
        parsed = urlparse(filename)
        # Get the last part of the path
        actual_filename = parsed.path.split("/")[-1]
    else:
        actual_filename = filename

    # Try to download from Supabase first (permanent access via service key)
    image_data = supabase.download_screenshot(run_id, actual_filename)
    if image_data:
        return image_data

    # Fallback to local file storage
    path = config.SCREENSHOTS_DIR / run_id / actual_filename
    if path.exists():
        with open(path, 'rb') as f:
            return f.read()

    raise HTTPException(status_code=404, detail="Screenshot not found")
