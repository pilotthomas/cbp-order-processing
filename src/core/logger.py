"""Application logger."""

from __future__ import annotations

import logging
import os
import sys
import traceback

import src.core.env_load  # noqa: F401 - load .env on startup

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

_LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
_IN_FUNCTIONS_WORKER = os.getenv("FUNCTIONS_WORKER_RUNTIME") == "python"

logger = logging.getLogger("app")
logger.setLevel(_LOG_LEVEL)
logger.propagate = True

if _IN_FUNCTIONS_WORKER:
    logging.getLogger().setLevel(_LOG_LEVEL)

if not _IN_FUNCTIONS_WORKER and not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(_handler)

for _name in ("azure", "urllib3", "httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def log_exception(message: str, exc: BaseException | None = None) -> None:
    """Log *message* with a full stack trace."""
    if exc is not None:
        detail = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ).rstrip()
    else:
        detail = traceback.format_exc().rstrip()
    if detail and detail != "NoneType: None":
        logger.error("%s\n%s", message, detail)
    else:
        logger.error("%s", message)
