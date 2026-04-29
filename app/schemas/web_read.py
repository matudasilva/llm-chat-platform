from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class WebReadOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    final_url: str
    content_type: str
    title: str | None = None
    text: str
    truncated: bool
