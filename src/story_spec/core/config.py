import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )
    
    # App
    APP_NAME: str = "StorySpec AI — Quiet Intelligence"
    APP_ENV: str = Field(default="development", alias="ENVIRONMENT")
    DEBUG: bool = Field(default=False)
    
    # Database
    DATABASE_URL: Optional[str] = None
    
    # JWT & Security
    JWT_SECRET_KEY: str = Field(default="your-secret-key-change-in-production")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # API
    API_V1_STR: str = "/api/v1"
    CORS_ORIGINS: list = ["*"]
    
    # Server
    HOST: str = "127.0.0.1"
    PORT: int = 7788
    RELOAD: bool = Field(default=True)
    
    # OpenRouter AI
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "openrouter/auto"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: Optional[str] = None

    # LangSmith tracing
    LANGSMITH_TRACING: bool = Field(default=False)
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROJECT: str = "story-spec"
    LANGSMITH_ENDPOINT: str = "https://api.smith.langchain.com"
    
    # Supabase
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    SUPABASE_BUCKET: str = "screenshots"
    
    # Email
    SMTP_SERVER: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SENDER_EMAIL: Optional[str] = None
    
    @property
    def screenshots_dir(self) -> Path:
        """Get screenshots directory path."""
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        screenshots_dir = base_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        return screenshots_dir

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.APP_ENV.lower() == "production"


# Load settings
settings = Settings()

# Keep backward compatibility with old imports
BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
SCREENSHOTS_DIR = settings.screenshots_dir
DATABASE_URL = settings.DATABASE_URL
OPENROUTER_API_KEY = settings.OPENROUTER_API_KEY
OPENROUTER_MODEL = settings.OPENROUTER_MODEL
OPENROUTER_BASE_URL = settings.OPENROUTER_BASE_URL
OPENROUTER_SITE_URL = settings.OPENROUTER_SITE_URL
LANGSMITH_TRACING = settings.LANGSMITH_TRACING
LANGSMITH_API_KEY = settings.LANGSMITH_API_KEY
LANGSMITH_PROJECT = settings.LANGSMITH_PROJECT
LANGSMITH_ENDPOINT = settings.LANGSMITH_ENDPOINT
SUPABASE_URL = settings.SUPABASE_URL
SUPABASE_KEY = settings.SUPABASE_KEY
SUPABASE_BUCKET = settings.SUPABASE_BUCKET
DASHBOARD_HOST = settings.HOST
DASHBOARD_PORT = settings.PORT

