from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int


def compute_backoff_ms(*, attempt: int, base_delay_ms: int, max_delay_ms: int) -> int:
    """
    Exponential backoff with capped delay and small jitter.

    attempt starts at 1.
    """
    exp = base_delay_ms * (2 ** (attempt - 1))
    capped = min(exp, max_delay_ms)
    jitter = random.randint(0, max(0, capped // 4))  # up to +25%
    return capped + jitter


async def retry_async(
    op: Callable[[int], Awaitable[T]],
    *,
    should_retry: Callable[[Exception], bool],
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await op(attempt)
        except Exception as exc:
            last_exc = exc
            if attempt >= policy.max_attempts or not should_retry(exc):
                raise
            delay_ms = compute_backoff_ms(
                attempt=attempt,
                base_delay_ms=policy.base_delay_ms,
                max_delay_ms=policy.max_delay_ms,
            )
            await sleep(delay_ms / 1000.0)

    assert last_exc is not None
    raise last_exc