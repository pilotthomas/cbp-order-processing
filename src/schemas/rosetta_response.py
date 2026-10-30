from typing import Any

from pydantic import BaseModel


class RosettaResponse(BaseModel):
    success: bool
    error_status: str
    error_message: str | None = None
    order: dict[str, Any] | None = None