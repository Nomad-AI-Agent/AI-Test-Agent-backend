from langchain_openai import ChatOpenAI
from openai import RateLimitError, BadRequestError
from pydantic import SecretStr

from story_spec.core import config


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
    return ChatOpenAI(
        api_key=SecretStr(config.OPENROUTER_API_KEY),
        base_url=config.OPENROUTER_BASE_URL,
        default_headers=_default_headers(),
        model=config.OPENROUTER_MODEL,
        temperature=temperature,
        max_retries=0,
    )


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
