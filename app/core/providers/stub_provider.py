from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import AsyncIterator, Literal

from app.core.domain.provider import (
    ProviderInput,
    ProviderPort,
    ProviderResult,
    ProviderStreamResult,
    ProviderStreamSession,
)
from app.core.domain.provider_prompt import messages_for_provider


@dataclass(slots=True)
class StubProvider(ProviderPort):
    """
    Deterministic stub provider.

    - No external IO
    - Optional simulated latency
    - Optional deterministic failure mode
    """
    provider: str = "stub"
    model_version: str = "stub-1"
    prompt_version: str = "stub-prompt-1"

    simulated_latency_ms: int = 0
    mode: Literal["ok", "error"] = "ok"

    async def generate(self, input: ProviderInput) -> ProviderResult:
        started_at = time.perf_counter()

        if self.simulated_latency_ms > 0:
            await asyncio.sleep(self.simulated_latency_ms / 1000)

        if self.mode == "error":
            raise RuntimeError("StubProvider simulated error")

        messages = messages_for_provider(input)
        last = messages[-1].content if messages else ""
        seed = f"{input.request_id}:{last}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()[:12]

        content = f"[stub:{digest}] {last}".strip()

        # Deterministic-ish minimal token estimation (words-based)
        input_text = " ".join(m.content for m in messages)
        in_tok = max(1, len(input_text.split())) if input_text else 0
        out_tok = max(1, len(content.split())) if content else 0

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)

        return ProviderResult(
            content=content,
            provider=self.provider,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=(in_tok + out_tok) if (in_tok and out_tok) else None,
            latency_ms=elapsed_ms,
            raw={"digest": digest, "mode": self.mode},
        )
        
    async def stream(self, input: ProviderInput) -> ProviderStreamSession:
        result = await self.generate(input)

        parts = result.content.split()

        async def chunk_iterator() -> AsyncIterator[str]:
            for part in parts:
                if self.simulated_latency_ms > 0:
                    await asyncio.sleep(self.simulated_latency_ms / 1000)
                yield part + " "

        async def get_final_result() -> ProviderStreamResult:
            return ProviderStreamResult(
                content=result.content,
                provider_result=result,
            )

        return ProviderStreamSession(
            chunks=chunk_iterator(),
            get_final_result=get_final_result,
        )
