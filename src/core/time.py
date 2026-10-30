from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import src.core.env_load  # noqa: F401 - load .env before reading TIME_ZONE
from src.core.config import get_time_zone_name


def get_time_zone() -> ZoneInfo:
    """Business zone from TIME_ZONE. Default America/Chicago."""
    name = get_time_zone_name()
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(
            f"TIME_ZONE {name!r} is not a valid IANA time zone"
        ) from exc


def now_chicago() -> datetime:
    """Naive TIME_ZONE timestamp for DATETIME2 columns."""
    return datetime.now(get_time_zone()).replace(tzinfo=None)


def format_rosetta_date(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(get_time_zone())
        return value.strftime("%Y%m%d")
    return value.strftime("%Y%m%d")
