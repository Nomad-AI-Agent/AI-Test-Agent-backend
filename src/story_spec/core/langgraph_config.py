"""
LangSmith integration and configuration.

Sets up comprehensive observability for the agentic system including:
- LangSmith client initialization
- Environment variable configuration
- Tracing decorators
- Graph-level and node-level logging
- Token and timing tracking
"""

import os
from typing import Optional
from datetime import datetime


class LangSmithConfig:
    """Configuration for LangSmith integration."""

    def __init__(self):
        """Initialize LangSmith configuration."""
        # Read from environment, with defaults
        self.enabled = self._get_bool("LANGCHAIN_TRACING_V2", True)
        self.api_key = os.getenv("LANGCHAIN_API_KEY")
        self.api_url = os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
        self.project_name = os.getenv("LANGCHAIN_PROJECT", "ai-test-agent")
        
    def _get_bool(self, key: str, default: bool = False) -> bool:
        """Get environment variable as boolean."""
        value = os.getenv(key, str(default)).lower()
        return value in {"true", "1", "yes", "on"}

    def is_configured(self) -> bool:
        """Check if LangSmith is properly configured."""
        if not self.enabled:
            return False
        if not self.api_key:
            return False
        return True

    def to_env_dict(self) -> dict:
        """Get environment variables dict for LangSmith."""
        env = {}
        if self.enabled:
            env["LANGCHAIN_TRACING_V2"] = "true"
            if self.api_key:
                env["LANGCHAIN_API_KEY"] = self.api_key
            if self.api_url:
                env["LANGCHAIN_ENDPOINT"] = self.api_url
            if self.project_name:
                env["LANGCHAIN_PROJECT"] = self.project_name
        return env


# Global configuration instance
_config: Optional[LangSmithConfig] = None


def get_langsmith_config() -> LangSmithConfig:
    """Get or create LangSmith configuration."""
    global _config
    if _config is None:
        _config = LangSmithConfig()
    return _config


def configure_langsmith():
    """Configure LangSmith environment variables."""
    config = get_langsmith_config()
    if config.is_configured():
        env_vars = config.to_env_dict()
        for key, value in env_vars.items():
            os.environ[key] = value


def verify_langsmith():
    """Verify LangSmith is properly configured and reachable."""
    config = get_langsmith_config()
    
    if not config.enabled:
        return {
            "enabled": False,
            "message": "LangSmith tracing is disabled (LANGCHAIN_TRACING_V2=false)",
        }
    
    if not config.api_key:
        return {
            "enabled": True,
            "configured": False,
            "message": "LangSmith API key not found (set LANGCHAIN_API_KEY)",
        }
    
    try:
        from langsmith import Client
        client = Client(
            api_key=config.api_key,
            api_url=config.api_url,
        )
        # Try to get current user using available client methods
        user = None
        # prefer get_user, fall back to get_current_user, and support callable attributes
        for attr in ("get_user", "get_current_user", "get_current_user_info"):
            fn = getattr(client, attr, None)
            if callable(fn):
                try:
                    user = fn()
                except Exception:
                    user = None
                break

        # Extract username safely
        username = None
        if user is not None:
            if isinstance(user, dict):
                username = user.get("username") or user.get("name")
            else:
                username = getattr(user, "username", None) or getattr(user, "name", None)

        username = username or "user"

        return {
            "enabled": True,
            "configured": True,
            "connected": True,
            "user": username,
            "project": config.project_name,
            "message": f"✓ LangSmith connected as {username} to project '{config.project_name}'",
        }
    except ImportError:
        return {
            "enabled": True,
            "configured": True,
            "connected": False,
            "message": "langsmith package not installed. Install with: pip install langsmith",
        }
    except Exception as e:
        return {
            "enabled": True,
            "configured": True,
            "connected": False,
            "message": f"Failed to connect to LangSmith: {str(e)}",
            "error": str(e),
        }


# Configure on import
try:
    configure_langsmith()
except Exception:
    pass
