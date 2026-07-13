from langchain_openai import ChatOpenAI
from openai import RateLimitError, BadRequestError
from pydantic import SecretStr

from story_spec.core import config
from story_spec.core import tracing

_client_cache: dict[float, ChatOpenAI] = {}
_langsmith_configured = False


def _ensure_langsmith():
    global _langsmith_configured
    if not _langsmith_configured:
        tracing.configure_langsmith_environment()
        _langsmith_configured = True


def _ascii_header_value(value: str) -> str:
    return value.encode("ascii", errors="ignore").decode("ascii").strip()


def _default_headers() -> dict[str, str]:
    headers = {}
    title = _ascii_header_value(config.settings.APP_NAME)
    if title:
        headers["X-OpenRouter-Title"] = title
    if config.OPENROUTER_SITE_URL:
        referer = _ascii_header_value(config.OPENROUTER_SITE_URL)
        if referer:
            headers["HTTP-Referer"] = referer
    return headers


def create_client(*, temperature: float = 0.0) -> ChatOpenAI:
    _ensure_langsmith()
    cached = _client_cache.get(temperature)
    if cached is not None:
        return cached
    client = ChatOpenAI(
        api_key=SecretStr(config.OPENROUTER_API_KEY),
        base_url=config.OPENROUTER_BASE_URL,
        default_headers=_default_headers(),
        model=config.OPENROUTER_MODEL,
        temperature=temperature,
        max_tokens=4096,
        max_retries=0,
    )
    _client_cache[temperature] = client
    return client


def message_content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                parts.append(text if isinstance(text, str) else str(item))
            else:
                parts.append(str(item))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


__all__ = ["ChatOpenAI", "RateLimitError", "BadRequestError", "create_client", "message_content_to_text"]
