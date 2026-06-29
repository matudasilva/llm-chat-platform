import asyncio
import uuid

from app.core.domain.chat_service import ChatService
from app.core.domain.chat_types import ChatMessage
from app.core.providers.stub_provider import StubProvider


def extract_digest(text: str) -> str:
    # Expected format: "[stub:<digest>] ..."
    prefix = "[stub:"
    if not text.startswith(prefix):
        raise ValueError(f"unexpected stub format: {text!r}")
    end = text.find("]")
    if end == -1:
        raise ValueError(f"missing closing bracket: {text!r}")
    return text[len(prefix):end]


async def main() -> None:
    provider = StubProvider(simulated_latency_ms=0, mode="ok")
    service = ChatService(provider)

    # Same request_id, same input -> same output
    fixed_request_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    messages = [ChatMessage(role="user", content="Hola, probando determinismo.")]

    r1 = await service.run(request_id=fixed_request_id, messages=messages)
    r2 = await service.run(request_id=fixed_request_id, messages=messages)

    d1 = extract_digest(r1.assistant_message.content)
    d2 = extract_digest(r2.assistant_message.content)

    print("=== DETERMINISM TEST ===")
    print("same request_id -> digest1:", d1)
    print("same request_id -> digest2:", d2)
    print("same output:", d1 == d2)

    # Different request_id, same input -> different output (almost surely; deterministic hash)
    other_request_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    r3 = await service.run(request_id=other_request_id, messages=messages)
    d3 = extract_digest(r3.assistant_message.content)

    print("\n=== SENSITIVITY TEST ===")
    print("other request_id -> digest3:", d3)
    print("different from digest1:", d3 != d1)

    # Optional: show full messages for human inspection
    print("\n=== OUTPUTS ===")
    print("out1:", r1.assistant_message.content)
    print("out3:", r3.assistant_message.content)


if __name__ == "__main__":
    asyncio.run(main())
