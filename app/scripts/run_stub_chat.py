import asyncio
import uuid

from app.core.domain.chat_service import ChatService
from app.core.domain.chat_types import ChatMessage
from core.providers.stub_provider import StubProvider


async def run_ok() -> None:
    request_id = uuid.uuid4()

    provider = StubProvider(simulated_latency_ms=50, mode="ok")
    service = ChatService(provider)

    messages = [ChatMessage(role="user", content="Hola, probando el stub.")]

    result = await service.run(request_id=request_id, messages=messages)

    print("=== OK PATH ===")
    print("request_id:", result.request_id)
    print("assistant:", result.assistant_message.content)
    pr = result.provider_result
    print("provider:", pr.provider)
    print("model_version:", pr.model_version)
    print("prompt_version:", pr.prompt_version)
    print("tokens:", pr.input_tokens, pr.output_tokens, pr.total_tokens)
    print("latency_ms:", pr.latency_ms)
    print("raw:", pr.raw)


async def run_error() -> None:
    request_id = uuid.uuid4()

    provider = StubProvider(simulated_latency_ms=10, mode="error")
    service = ChatService(provider)

    messages = [ChatMessage(role="user", content="Esto debería fallar.")]

    print("\n=== ERROR PATH ===")
    try:
        await service.run(request_id=request_id, messages=messages)
    except Exception as e:
        print("request_id:", request_id)
        print("error:", repr(e))


async def main() -> None:
    await run_ok()
    await run_error()


if __name__ == "__main__":
    asyncio.run(main())
