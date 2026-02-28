import pytest

from app.core.utils.retry import RetryPolicy, retry_async


@pytest.mark.asyncio
async def test_retry_async_retries_until_success(monkeypatch):
    calls = {"n": 0}

    async def op(attempt: int) -> int:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return 42

    async def fake_sleep(_: float) -> None:
        return None

    def should_retry(exc: Exception) -> bool:
        return isinstance(exc, RuntimeError)

    policy = RetryPolicy(max_attempts=3, base_delay_ms=1, max_delay_ms=2)
    out = await retry_async(op, should_retry=should_retry, policy=policy, sleep=fake_sleep)

    assert out == 42
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_retry_async_does_not_retry_when_predicate_false(monkeypatch):
    calls = {"n": 0}

    async def op(attempt: int) -> int:
        calls["n"] += 1
        raise ValueError("non-retryable")

    async def fake_sleep(_: float) -> None:
        return None

    def should_retry(exc: Exception) -> bool:
        return False

    policy = RetryPolicy(max_attempts=5, base_delay_ms=1, max_delay_ms=2)

    with pytest.raises(ValueError):
        await retry_async(op, should_retry=should_retry, policy=policy, sleep=fake_sleep)

    assert calls["n"] == 1