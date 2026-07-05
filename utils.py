"""
Utility helpers: logging, retry decorator, JSON serialisation.

Keeps reusable cross-cutting concerns out of the main scraper module.
"""

import asyncio
import json
import logging
import os
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from config import CONFIG

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

#: Module-level logger – import and use via ``logger = get_logger(__name__)``
_loggers: dict = {}


def get_logger(name: str) -> logging.Logger:
    """
    Return a pre-configured logger for *name*.

    Logs are written both to stderr (INFO+) and to a rotating file.
    This function is idempotent – it reuses loggers already created.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (INFO and above)
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # File handler (DEBUG and above)
    os.makedirs("logs", exist_ok=True)
    fh = logging.FileHandler("logs/tiktok_scraper.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    _loggers[name] = logger
    return logger


# ---------------------------------------------------------------------------
# Retry decorator (async)
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])


def async_retry(
    max_attempts: int | None = None,
    base_delay_ms: int | None = None,
    backoff: float | None = None,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries an async function on failure.

    Parameters
    ----------
    max_attempts:
        Override for ``RetryConfig.max_attempts``.
    base_delay_ms:
        Override for ``RetryConfig.delay``.
    backoff:
        Override for ``RetryConfig.backoff_factor``.
    exceptions:
        Tuple of exception classes that trigger a retry.
    """
    max_attempts = max_attempts or CONFIG.retry.max_attempts
    base_delay_ms = base_delay_ms or CONFIG.timeout.retry_delay
    backoff = backoff or CONFIG.retry.backoff_factor

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(func.__module__)
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        delay = base_delay_ms * (backoff ** (attempt - 1))
                        logger.warning(
                            "%s attempt %d/%d failed: %s. "
                            "Retrying in %.0f ms …",
                            func.__name__,
                            attempt,
                            max_attempts,
                            exc,
                            delay,
                        )
                        await asyncio.sleep(delay / 1000)
                    else:
                        logger.error(
                            "%s failed after %d attempts.",
                            func.__name__,
                            max_attempts,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def save_json(data: Any, filepath: str | Path) -> Path:
    """
    Serialise *data* to JSON and write it to *filepath*.

    Creates parent directories as needed.  Returns the resolved path.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    logger = get_logger(__name__)
    logger.info("Data saved to %s", path.resolve())
    return path.resolve()


def load_json(filepath: str | Path) -> Any:
    """Load a JSON file and return its contents."""
    path = Path(filepath)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)
