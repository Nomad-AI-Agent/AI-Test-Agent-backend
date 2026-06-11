"""Request and response models for the API."""

from typing import Optional
from pydantic import BaseModel


class RunRequest(BaseModel):
    """Request to create and start a new test run."""
    url: str
    story: str
    headless: bool = True


class RunCancelRequest(BaseModel):
    """Request to cancel a running test."""
    reason: Optional[str] = "Run canceled by user."
