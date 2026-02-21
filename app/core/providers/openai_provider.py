from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.domain.provider import ProviderInput, ProviderPort, ProviderResult
from app.core.domain.provider_errors import ProviderError, ProviderErrorKind


@dataclass(frozen=True)
class OpenAIProviderConfig:
    api_key: str
    model: str
    timeout_s: float


class OpenAIProvider(ProviderPort):
    def __init__(
        self,
        config: OpenAIProviderConfig,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        base_url: str = "https://api.openai.com",
    ) -> None:
        self._cfg = config
        self._client = http_client
        self._base_url = base_url.rstrip("/")

    async def generate(self, input: ProviderInput) -> ProviderResult:
        start = time.monotonic()

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._cfg.model,
            "input": [
                {
                    "role": m.role,
                    "content": [{"type": "input_text", "text": m.content}],
                }
                for m in input.messages
            ],
        }

        client = self._client or httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(self._cfg.timeout_s),
        )

        try:
            r = await client.post("/v1/responses", json=payload)

            if r.status_code >= 400:
                raise _status_to_provider_error(r.status_code)

            data = r.json()
            content = _extract_output_text(data)
            usage = data.get("usage") or {}
            latency_ms = int((time.monotonic() - start) * 1000)

            return ProviderResult(
                content=content,
                provider="openai",
                model_version=self._cfg.model,
                prompt_version="v1",
                input_tokens=_safe_int(usage.get("input_tokens")),
                output_tokens=_safe_int(usage.get("output_tokens")),
                total_tokens=_safe_int(usage.get("total_tokens")),
                latency_ms=latency_ms,
            )

        except httpx.TimeoutException as e:
            raise ProviderError(ProviderErrorKind.timeout, "provider timeout") from e
        except httpx.RequestError as e:
            raise ProviderError(ProviderErrorKind.upstream, "provider upstream error") from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(ProviderErrorKind.unknown, "provider unknown error") from e
        finally:
            if self._client is None:
                await client.aclose()


def _status_to_provider_error(status: int) -> ProviderError:
    if status in (401, 403):
        return ProviderError(ProviderErrorKind.auth, "provider auth failed")
    if status == 429:
        return ProviderError(ProviderErrorKind.rate_limit, "provider rate limited")
    if 500 <= status <= 599:
        return ProviderError(ProviderErrorKind.upstream, "provider upstream error")
    return ProviderError(ProviderErrorKind.unknown, "provider request failed")


def _extract_output_text(data: dict[str, Any]) -> str:
    out = data.get("output") or []
    chunks: list[str] = []
    for item in out:
        if item.get("type") != "message":
            continue
        if item.get("role") != "assistant":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    text = "".join(chunks).strip()
    return text if text else "(empty response)"


def _safe_int(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except Exception:
        return None