import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from langsmith.run_helpers import tracing_context
from langchain_core.runnables import RunnableConfig

from story_spec.core import config


def tracing_enabled() -> bool:
    return bool(config.LANGSMITH_TRACING and config.LANGSMITH_API_KEY)


def configure_langsmith_environment() -> None:
    if not tracing_enabled():
        return
    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGSMITH_API_KEY", config.LANGSMITH_API_KEY or "")
    os.environ.setdefault("LANGSMITH_PROJECT", config.LANGSMITH_PROJECT)
    os.environ.setdefault("LANGSMITH_ENDPOINT", config.LANGSMITH_ENDPOINT)


def runnable_config(
    run_name: str,
    *,
    run_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> RunnableConfig:
    if not tracing_enabled():
        return {"run_name": run_name}

    merged_metadata = dict(metadata or {})
    if run_id:
        merged_metadata["test_run_id"] = run_id

    return {
        "run_name": run_name,
        "tags": ["story-spec", *(tags or [])],
        "metadata": merged_metadata,
    }


@contextmanager
def trace_context(
    *,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Iterator[None]:
    configure_langsmith_environment()
    with tracing_context(
        project_name=config.LANGSMITH_PROJECT,
        tags=["story-spec", *(tags or [])],
        metadata=metadata or {},
        enabled=tracing_enabled(),
    ):
        yield
