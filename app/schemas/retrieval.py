# app/schemas/retrieval.py
from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_n: int | None = Field(default=None, gt=0)


class RetrievedChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chunk_id: UUID
    document_id: UUID
    text: str
    rank: int


class RetrieveResponse(BaseModel):
    query: str
    rewritten_query: str
    chunks: list[RetrievedChunkOut]
    fallback_triggered: bool
    evaluator_triggered: bool
    evaluator_verdict: str | None
