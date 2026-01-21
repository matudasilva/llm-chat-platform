# app/infra/schemas/trace.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Importá tus schemas existentes (ajustá nombres según tus archivos reales)
from app.infra.schemas.usage_events import UsageEventOut
from app.infra.schemas.conversations import ConversationSummary, MessageOut


class CheckResultOut(BaseModel):
    name: str
    ok: bool
    detail: Optional[str] = None


class CoherenceOut(BaseModel):
    checks: list[CheckResultOut] = []
    warnings: list[str] = []
    errors: list[str] = []


class ReconstructionOut(BaseModel):
    input_message: Optional[MessageOut] = None
    output_message: Optional[MessageOut] = None


class TraceReportOut(BaseModel):
    """
    Reporte interno (no endpoint) para reconstrucción end-to-end por request_id.
    """
    model_config = ConfigDict(from_attributes=True)

    request_id: UUID
    events: list[UsageEventOut]
    primary_event: UsageEventOut

    conversation: Optional[ConversationSummary] = None
    messages: Optional[list[MessageOut]] = None

    reconstruction: Optional[ReconstructionOut] = None
    coherence: CoherenceOut
