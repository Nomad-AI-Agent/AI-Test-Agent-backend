from openai import OpenAI, RateLimitError, BadRequestError

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


def create_client() -> OpenAI:
    return OpenAI(
        api_key=config.OPENROUTER_API_KEY,
        base_url=config.OPENROUTER_BASE_URL,
        default_headers=_default_headers(),
    )


__all__ = ["OpenAI", "RateLimitError", "BadRequestError", "create_client"]
