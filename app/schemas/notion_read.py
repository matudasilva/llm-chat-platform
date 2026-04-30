"""
Pydantic schemas for Notion Read API responses.

Metadata-only MVP: page_id, title, url, created_time, last_edited_time.
No page text, blocks, or database content.
"""

from pydantic import BaseModel, ConfigDict


class NotionPageOut(BaseModel):
    """
    Notion page metadata (read-only response).

    Metadata-only MVP: no page text, blocks, or internal fields.
    Uses extra="forbid" to prevent accidental leakage of Notion-internal data.
    """

    model_config = ConfigDict(extra="forbid")

    page_id: str
    title: str | None = None
    url: str
    created_time: str | None = None
    last_edited_time: str | None = None
