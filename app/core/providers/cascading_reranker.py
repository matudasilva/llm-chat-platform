from __future__ import annotations

import logging
import time
from typing import Sequence

from app.core.domain.reranker import (
    RankedDocument,
    RerankerPort,
    RerankRequest,
    TerminalRerankerError,
    TransientRerankerError,
)

_LOGGER = logging.getLogger("app.reranker_cascade")
_BACKEND = "cascade"


class CascadingRerankerAdapter(RerankerPort):
    """Availability cascade: GCP primary, AWS fallback (ORQ-24 spec.md).

    GCP is primary because AWS Bedrock Rerank's account-level quota is a hard,
    non-adjustable 2 requests/minute (aws_quota_finding.md) -- a real
    production ceiling, not a test-burst artifact. AWS stays as the fallback
    because ORQ-22's benchmark found no quality gap between backends.

    Cascade trigger (spec.md §Design decisions 2): a `TransientRerankerError`
    from GCP, or any other exception from the GCP call specifically (a
    defensive boundary catch -- `GcpReranker`, unlike `AwsReranker`, has no
    blanket exception normalization; fixing that is out of this ORQ's scope).
    A `TerminalRerankerError` from GCP is GCP's own explicit "this is a
    configuration fault" signal and propagates directly without trying AWS.
    If AWS also fails, its `RerankerError` propagates so `RetrievalPipeline`'s
    existing fallback to RRF order applies unchanged.

    Never retries within a single provider; one attempt per provider only.
    """

    def __init__(self, *, primary: RerankerPort, fallback: RerankerPort) -> None:
        self._primary = primary
        self._fallback = fallback

    async def rerank(self, request: RerankRequest) -> Sequence[RankedDocument]:
        start = time.monotonic()
        try:
            results = await self._primary.rerank(request)
        except TerminalRerankerError:
            # GCP's own explicit "configuration fault" signal -- AWS cannot
            # resolve a broken GCP credential/project, so do not cascade.
            self._log(
                primary_ok=False,
                fallback_attempted=False,
                error_code=None,
                latency_s=time.monotonic() - start,
            )
            raise
        except TransientRerankerError as exc:
            self._log(
                primary_ok=False,
                fallback_attempted=True,
                error_code=exc.error_code or "transient",
                latency_s=time.monotonic() - start,
            )
            return await self._attempt_fallback(request)
        except Exception:
            # Defensive boundary catch: GcpReranker has no blanket exception
            # normalization (spec.md §Design decisions 2), so an unexpected
            # failure inside it must not silently bypass the cascade. Scoped
            # to the primary (GCP) call only -- never applied to the AWS call
            # below, whose adapter is already fully normalized.
            self._log(
                primary_ok=False,
                fallback_attempted=True,
                error_code="unnormalized",
                latency_s=time.monotonic() - start,
            )
            return await self._attempt_fallback(request)
        else:
            self._log(
                primary_ok=True,
                fallback_attempted=False,
                error_code=None,
                latency_s=time.monotonic() - start,
            )
            return results

    async def _attempt_fallback(self, request: RerankRequest) -> Sequence[RankedDocument]:
        # AWS's own adapter fully normalizes every failure into
        # TransientRerankerError/TerminalRerankerError (verified, spec.md
        # §Design decisions 2) -- whatever it raises here is already a
        # RerankerError and propagates as-is for RetrievalPipeline's fallback.
        return await self._fallback.rerank(request)

    def _log(
        self,
        *,
        primary_ok: bool,
        fallback_attempted: bool,
        error_code: str | None,
        latency_s: float | None = None,
    ) -> None:
        # Best-effort, content-free (no query text, no document content):
        # a logging failure here can never break the cascade itself.
        try:
            _LOGGER.info(
                "reranker_cascade",
                extra={
                    "backend": _BACKEND,
                    "primary_ok": primary_ok,
                    "fallback_attempted": fallback_attempted,
                    "error_code": error_code,
                    "latency_s": latency_s,
                },
            )
        except Exception:  # pragma: no cover - logging must never raise
            pass
