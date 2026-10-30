"""Load ``.env`` from the repository root into ``os.environ``.

``override=False``: variables already set — including Azure Functions
``local.settings.json`` Values — are not replaced by ``.env``.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment,misc]

if load_dotenv is not None:
    load_dotenv(_REPO_ROOT / ".env", override=False)
