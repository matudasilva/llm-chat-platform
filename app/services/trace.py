# app/services/trace.py
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.usage_event import UsageEvent
from app.models.conversation import Conversation
from app.models.message import Message

from app.infra.schemas.usage_events import UsageEventOut
from app.infra.schemas.conversations import ConversationSummary, MessageOut
from app.infra.schemas.trace import (
    TraceReportOut,
    CoherenceOut,
    CheckResultOut,
    ReconstructionOut,
)


class TraceService:
    @staticmethod
    async def reconstruct_by_request_id(db: AsyncSession, request_id: UUID) -> TraceReportOut:
        coherence = CoherenceOut()

        # 1) Buscar usage events del request_id
        events_stmt = (
            select(UsageEvent)
            .where(UsageEvent.request_id == request_id)
            .order_by(UsageEvent.timestamp.desc(), UsageEvent.id.desc())
        )
        events = (await db.execute(events_stmt)).scalars().all()

        if not events:
            coherence.errors.append("No UsageEvent found for request_id")
            coherence.checks.append(CheckResultOut(name="usage_event_found", ok=False))
            # En modo script, esto lo podés tratar como excepción; aquí lo dejo como ValueError
            raise ValueError(f"No UsageEvent found for request_id={request_id}")

        coherence.checks.append(CheckResultOut(name="usage_event_found", ok=True))

        if len(events) > 1:
            coherence.warnings.append("Multiple UsageEvents found for same request_id (using primary_event selection rule).")
            coherence.checks.append(CheckResultOut(name="single_usage_event", ok=False, detail=f"count={len(events)}"))
        else:
            coherence.checks.append(CheckResultOut(name="single_usage_event", ok=True))

        # 2) Elegir primary_event: preferir success si existe, si no el más reciente
        primary = _select_primary_event(events)

        # Convertir a schema out
        events_out = [UsageEventOut.model_validate(e) for e in events]
        primary_out = UsageEventOut.model_validate(primary)

        # 3) Checks de FKs según tu invariante
        # success -> FKs presentes; error -> best-effort
        # Ajustá la comparación si tu status es enum / valores distintos
        status_value = getattr(primary, "status", None)
        is_success = _norm_str_enum(status_value) == "success"

        if is_success:
            missing = []
            if getattr(primary, "conversation_id", None) is None:
                missing.append("conversation_id")
            if getattr(primary, "message_id", None) is None:
                missing.append("message_id")

            if missing:
                coherence.errors.append(f"Success UsageEvent is missing FKs: {', '.join(missing)}")
                coherence.checks.append(CheckResultOut(name="success_has_fks", ok=False, detail="missing=" + ",".join(missing)))
            else:
                coherence.checks.append(CheckResultOut(name="success_has_fks", ok=True))
        else:
            coherence.checks.append(CheckResultOut(name="success_has_fks", ok=True, detail="status!=success (best-effort allowed)"))

        # 4) Resolver conversación y mensajes (si hay conversation_id)
        conv_out: Optional[ConversationSummary] = None
        msgs_out: Optional[list[MessageOut]] = None
        reconstruction: Optional[ReconstructionOut] = None

        conversation_id = getattr(primary, "conversation_id", None)
        message_id = getattr(primary, "message_id", None)

        conversation_obj: Optional[Conversation] = None
        messages: list[Message] = []

        if conversation_id is not None:
            conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
            conversation_obj = (await db.execute(conv_stmt)).scalar_one_or_none()

            if conversation_obj is None:
                coherence.errors.append("conversation_id is present in UsageEvent but Conversation not found (FK inconsistency).")
                coherence.checks.append(CheckResultOut(name="conversation_found", ok=False))
            else:
                coherence.checks.append(CheckResultOut(name="conversation_found", ok=True))
                conv_out = ConversationSummary.model_validate(conversation_obj)

                msgs_stmt = (
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.asc(), Message.id.asc())
                )
                messages = (await db.execute(msgs_stmt)).scalars().all()

                if not messages:
                    coherence.warnings.append("Conversation found but has no messages.")
                    coherence.checks.append(CheckResultOut(name="messages_loaded", ok=False, detail="count=0"))
                    msgs_out = []
                else:
                    coherence.checks.append(CheckResultOut(name="messages_loaded", ok=True, detail=f"count={len(messages)}"))
                    msgs_out = [MessageOut.model_validate(m) for m in messages]

                # 5) Reconstrucción input/output
                if messages:
                    reconstruction = _reconstruct_pair(messages=messages, output_message_id=message_id)
                    if reconstruction.input_message is None or reconstruction.output_message is None:
                        coherence.warnings.append("Unable to reconstruct complete input/output pair (best-effort).")
                        coherence.checks.append(CheckResultOut(name="input_output_resolved", ok=False))
                    else:
                        coherence.checks.append(CheckResultOut(name="input_output_resolved", ok=True))
        else:
            coherence.checks.append(CheckResultOut(name="conversation_found", ok=True, detail="conversation_id is null (allowed for error/best-effort)"))

        return TraceReportOut(
            request_id=request_id,
            events=events_out,
            primary_event=primary_out,
            conversation=conv_out,
            messages=msgs_out,
            reconstruction=reconstruction,
            coherence=coherence,
        )


def _select_primary_event(events: list[UsageEvent]) -> UsageEvent:
    # Preferir success si existe; si no, el primero (ya viene ordered desc)
    for e in events:
        status_value = getattr(e, "status", None)
        if str(status_value).lower() == "success":
            return e
    return events[0]


def _norm_str_enum(v) -> str:
    """
    Normaliza strings/enums del tipo MessageRole.user o UsageStatus.success -> "user"/"success".
    """
    if v is None:
        return ""
    # Enum: .value suele ser "user"/"assistant"/"success"
    if hasattr(v, "value"):
        v = v.value
    s = str(v).strip().lower()
    # Si viene "messagerole.user" o "status.success", quedarse con lo último
    if "." in s:
        s = s.split(".")[-1]
    return s


def _reconstruct_pair(messages: list[Message], output_message_id: Optional[UUID]) -> ReconstructionOut:
    """
    Best-effort:
    - Si output_message_id existe: output = ese; input = user anterior.
    - Si no: output = último assistant; input = user anterior.
    """
    # Helper para convertir Message -> MessageOut
    def to_out(m: Optional[Message]) -> Optional[MessageOut]:
        return MessageOut.model_validate(m) if m is not None else None

    output_msg: Optional[Message] = None
    input_msg: Optional[Message] = None

    # Caso 1: output explícito por message_id
    if output_message_id is not None:
        for m in messages:
            if m.id == output_message_id:
                output_msg = m
                break

        if output_msg is not None:
            out_idx: int | None = None
            for i, m in enumerate(messages):
                if m.id == output_msg.id:
                    out_idx = i
                    break

        if out_idx is not None:
            # buscar hacia atrás el último role=user
            for j in range(out_idx - 1, -1, -1):
                if _norm_str_enum(getattr(messages[j], "role", None)) == "user":
                    input_msg = messages[j]
                    break

        return ReconstructionOut(input_message=to_out(input_msg), output_message=to_out(output_msg))


    # Caso 2: fallback: último assistant + user anterior
    for i in range(len(messages) - 1, -1, -1):
        if _norm_str_enum(getattr(messages[i], "role", None)) == "assistant":
            output_msg = messages[i]
            # buscar user anterior
            for j in range(i - 1, -1, -1):
                if str(getattr(messages[j], "role", "")).lower() == "user":
                    input_msg = messages[j]
                    break
            break

    return ReconstructionOut(input_message=to_out(input_msg), output_message=to_out(output_msg))
