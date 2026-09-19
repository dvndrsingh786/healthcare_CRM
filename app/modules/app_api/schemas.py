from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import StringConstraints

from app.schemas import Out, StrictModel


class DeviceRegister(StrictModel):
    platform: Literal["IOS", "ANDROID", "WEB"]
    push_token: Annotated[str, StringConstraints(min_length=16, max_length=4096, pattern=r"^[\x21-\x7e]+$")]
    device_name: Annotated[str, StringConstraints(max_length=100)] | None = None

    model_config = {"json_schema_extra": {"examples": [{
        "platform": "IOS", "push_token": "f3a9c1e0b7d24c8e9a6b5d4c3b2a1f0e9d8c7b6a", "device_name": "Maggie's iPhone",
    }]}}


class DeviceOut(Out):
    """The push token itself is never returned."""
    id: UUID
    platform: str
    device_name: str | None
    created_at: datetime
    last_seen_at: datetime
