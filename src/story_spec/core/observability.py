"""
Observability utilities for the agentic system.

Provides decorators, logging, and tracing utilities that integrate
with LangSmith for comprehensive monitoring and debugging.
"""

import time
import logging
import os
from typing import Any, Callable, Optional, Dict, TypeVar, Coroutine
from functools import wraps
from datetime import datetime

try:
    from langsmith import traceable, Client
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    # Fallback if langsmith not available
    def traceable(*args, **kwargs):
        """Fallback decorator when LangSmith is not installed."""
        def decorator(func):
            return func
        
        # Handle both @traceable and @traceable(name="...", run_type="...")
        if len(args) == 1 and callable(args[0]):
            # @traceable without arguments
            return args[0]
        else:
            # @traceable(name="...", run_type="...")
            return decorator
    
    Client = None


logger = logging.getLogger(__name__)


F = TypeVar("F", bound=Callable[..., Any])


def setup_langsmith():
    """Initialize LangSmith tracing from environment variables."""
    if not LANGSMITH_AVAILABLE:
        logger.warning("LangSmith not installed. Tracing disabled.")
        return
    
    # Load environment variables
    tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    api_key = os.getenv("LANGSMITH_API_KEY")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com")
    project = os.getenv("LANGSMITH_PROJECT", "default")
    
    if not tracing_enabled:
        logger.info("LangSmith tracing disabled (LANGSMITH_TRACING=false)")
        return
    
    if not api_key:
        logger.warning("LangSmith API key not found. Tracing disabled.")
        return
    
    # Set environment variables for LangSmith
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = api_key
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_PROJECT"] = project
    
    logger.info(f"✓ LangSmith tracing initialized")
    logger.info(f"  - Endpoint: {endpoint}")
    logger.info(f"  - Project: {project}")


def setup_logging(level: int = logging.INFO):
    """Setup logging for the agentic system."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def log_node_execution(node_name: str):
    """Decorator to log node execution with timing."""
    def decorator(func: F) -> F:
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            logger.info(f"[{node_name}] Starting execution")
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(f"[{node_name}] Completed in {elapsed_ms:.0f}ms")
                return result
            except Exception as e:
                elapsed_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"[{node_name}] Failed after {elapsed_ms:.0f}ms: {str(e)}"
                )
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            logger.info(f"[{node_name}] Starting execution")
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(f"[{node_name}] Completed in {elapsed_ms:.0f}ms")
                return result
            except Exception as e:
                elapsed_ms = (time.time() - start_time) * 1000
                logger.error(
                    f"[{node_name}] Failed after {elapsed_ms:.0f}ms: {str(e)}"
                )
                raise

        # Return appropriate wrapper based on function type
        if hasattr(func, "__name__") and "async" in str(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class ExecutionTimer:
    """Context manager for tracking execution timing."""

    def __init__(self, name: str = "Operation"):
        self.name = name
        self.start_time: Optional[float] = None
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "ExecutionTimer":
        self.start_time = time.time()
        logger.debug(f"[{self.name}] Starting")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.elapsed_ms = (time.time() - self.start_time) * 1000
        if exc_type:
            logger.error(
                f"[{self.name}] Failed after {self.elapsed_ms:.0f}ms: {exc_val}"
            )
        else:
            logger.debug(f"[{self.name}] Completed in {self.elapsed_ms:.0f}ms")


def snapshot_state(name: str, state: Dict[str, Any]) -> None:
    """Log a snapshot of the state."""
    # Create a summary that avoids logging large binary objects
    summary = {
        "run_id": state.get("run_id"),
        "step_index": state.get("step_index"),
        "goal_achieved": state.get("goal_achieved"),
        "max_steps_reached": state.get("max_steps_reached"),
        "last_action_success": state.get("last_action_success"),
        "failure_count": state.get("failure_count"),
        "action_history_len": len(state.get("action_history", [])),
    }
    logger.debug(f"[{name}] State snapshot: {summary}")


class GraphMetrics:
    """Track metrics for the graph execution."""

    def __init__(self):
        self.start_time: Optional[datetime] = None
        self.node_timings: Dict[str, float] = {}
        self.total_tokens: int = 0
        self.step_count: int = 0
        self.failures: int = 0

    def start(self) -> None:
        """Start tracking."""
        self.start_time = datetime.now()

    def record_node(self, node_name: str, elapsed_ms: float) -> None:
        """Record node execution time."""
        if node_name not in self.node_timings:
            self.node_timings[node_name] = 0.0
        self.node_timings[node_name] += elapsed_ms
        logger.debug(f"Node '{node_name}' took {elapsed_ms:.0f}ms")

    def record_tokens(self, count: int) -> None:
        """Record token usage."""
        self.total_tokens += count

    def record_step(self) -> None:
        """Record a completed step."""
        self.step_count += 1

    def record_failure(self) -> None:
        """Record a failure."""
        self.failures += 1

    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary."""
        elapsed_ms = 0.0
        if self.start_time:
            elapsed_ms = (datetime.now() - self.start_time).total_seconds() * 1000

        return {
            "total_duration_ms": elapsed_ms,
            "total_steps": self.step_count,
            "total_failures": self.failures,
            "total_tokens": self.total_tokens,
            "node_timings": self.node_timings,
            "avg_step_duration_ms": elapsed_ms / max(1, self.step_count),
        }

    def log_summary(self) -> None:
        """Log metrics summary."""
        summary = self.get_summary()
        logger.info("=== EXECUTION METRICS ===")
        logger.info(f"Total duration: {summary['total_duration_ms']:.0f}ms")
        logger.info(f"Total steps: {summary['total_steps']}")
        logger.info(f"Total failures: {summary['total_failures']}")
        logger.info(f"Total tokens: {summary['total_tokens']}")
        logger.info(f"Avg step duration: {summary['avg_step_duration_ms']:.0f}ms")


# Global metrics instance
_metrics: Optional[GraphMetrics] = None


def get_metrics() -> GraphMetrics:
    """Get or create metrics instance."""
    global _metrics
    if _metrics is None:
        _metrics = GraphMetrics()
    return _metrics


def reset_metrics() -> None:
    """Reset metrics for new run."""
    global _metrics
    _metrics = GraphMetrics()
