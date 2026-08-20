"""Normative SHA-256 derivation and registered 48-or-stop selector arithmetic."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import statistics
from typing import Callable

UINT64_SPACE = 2**64
MAX_REJECTION_REHASHES = 1_024
SANITY_UNIFORM_PREFIX = "ORQ-30|mve-v2|selector-normal-power|v1"
SANITY_BOOTSTRAP_PREFIX = "ORQ-30|mve-v2|selector-inner-bootstrap|v1"
CONFIRMATORY_BOOTSTRAP_PREFIX = (
    "ORQ-30|mve-v2|confirmatory-primary-bootstrap|v1"
)


class DeterminismIntegrityError(RuntimeError):
    """A normative numeric or domain invariant failed."""


def unsigned_decimal(value: int) -> str:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("domain integers must be unsigned integers")
    return str(value)


def join_domain(prefix: str, *values: int) -> str:
    """Append canonical unsigned decimal fields with literal U+007C separators."""

    if not isinstance(prefix, str) or not prefix:
        raise ValueError("domain prefix must be non-empty text")
    prefix.encode("utf-8", errors="strict")
    return "|".join((prefix, *(unsigned_decimal(value) for value in values)))


def first_uint64(payload: bytes) -> int:
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


def open_binary64_uniform_from_x(x: int) -> float:
    if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < UINT64_SPACE:
        raise ValueError("x must be an unsigned 64-bit integer")
    k = x >> 11
    u = (k + 1) / (2**53 + 1)
    assert 0.0 < u < 1.0
    return u


def open_binary64_uniform(domain: str) -> float:
    return open_binary64_uniform_from_x(first_uint64(domain.encode("utf-8")))


def unbiased_zero_based_index(
    base_domain: str,
    n: int,
    *,
    derive_x: Callable[[bytes], int] = first_uint64,
) -> int:
    """Select without modulo bias using deterministic rejection and counter fields."""

    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= UINT64_SPACE:
        raise ValueError("n must satisfy 1 <= n <= 2**64")
    base_bytes = base_domain.encode("utf-8", errors="strict")
    limit = UINT64_SPACE - (UINT64_SPACE % n)
    rejection_counter = 0
    while True:
        payload = (
            base_bytes
            if rejection_counter == 0
            else base_bytes + b"|" + unsigned_decimal(rejection_counter).encode("ascii")
        )
        x = derive_x(payload)
        if isinstance(x, bool) or not isinstance(x, int) or not 0 <= x < UINT64_SPACE:
            raise DeterminismIntegrityError("SHA-256 derivation returned invalid uint64")
        if x < limit:
            return x % n
        if rejection_counter >= MAX_REJECTION_REHASHES:
            raise DeterminismIntegrityError(
                "unbiased index exceeded the registered 1,024 rehash limit"
            )
        rejection_counter += 1


def sanity_uniform_domain(n: int, t: int, j: int) -> str:
    return join_domain(SANITY_UNIFORM_PREFIX, n, t, j)


def sanity_bootstrap_index(n: int, t: int, r: int, j: int) -> int:
    base = join_domain(SANITY_BOOTSTRAP_PREFIX, n, t, r, j)
    return unbiased_zero_based_index(base, n)


def confirmatory_bootstrap_index(n: int, r: int, j: int) -> int:
    base = join_domain(CONFIRMATORY_BOOTSTRAP_PREFIX, n, r, j)
    return unbiased_zero_based_index(base, n)


def sanity_bootstrap_replicate_mean(
    observations: tuple[float, ...], *, t: int, r: int
) -> float:
    """Compute one registered inner-bootstrap mean without running the simulation."""

    n = len(observations)
    if n not in {48, 64}:
        raise ValueError("sanity observations must contain 48 or 64 values")
    if any(not math.isfinite(value) for value in observations):
        raise DeterminismIntegrityError("sanity observations must be finite")
    selected = (
        observations[sanity_bootstrap_index(n, t, r, j)] for j in range(n)
    )
    mean = sum(selected) / n
    if not math.isfinite(mean):
        raise DeterminismIntegrityError("sanity bootstrap mean is not finite")
    return mean


def sanity_normal_observation(sigma_plan: float, *, n: int, t: int, j: int) -> float:
    """Generate one registered synthetic normal observation from its open uniform."""

    if n not in {48, 64}:
        raise ValueError("n must be 48 or 64")
    if not isinstance(sigma_plan, (int, float)) or isinstance(sigma_plan, bool):
        raise TypeError("sigma_plan must be numeric")
    sigma_plan = float(sigma_plan)
    if not math.isfinite(sigma_plan) or sigma_plan <= 0:
        raise DeterminismIntegrityError("sigma_plan must be finite and positive")
    u = open_binary64_uniform(sanity_uniform_domain(n, t, j))
    value = statistics.NormalDist(mu=0.10, sigma=sigma_plan).inv_cdf(u)
    if not math.isfinite(value):
        raise DeterminismIntegrityError("synthetic normal observation is not finite")
    return value


def sanity_inner_lower_bound(replicate_means: tuple[float, ...]) -> float:
    """Return the 50th smallest of exactly 1,000 means without interpolation."""

    if len(replicate_means) != 1_000:
        raise ValueError("sanity inner bootstrap requires exactly 1,000 means")
    if any(not math.isfinite(value) for value in replicate_means):
        raise DeterminismIntegrityError("sanity bootstrap means must be finite")
    return sorted(replicate_means)[49]


def sanity_acceptance_fraction(lower_bounds: tuple[float, ...]) -> float:
    """Return the fraction of 2,000 strict lower-bound successes."""

    if len(lower_bounds) != 2_000:
        raise ValueError("sanity power requires exactly 2,000 outer lower bounds")
    if any(not math.isfinite(value) for value in lower_bounds):
        raise DeterminismIntegrityError("sanity lower bounds must be finite")
    return sum(value > 0.05 for value in lower_bounds) / 2_000


def run_registered_local_sanity(sigma_plan: float, n: int) -> float:
    """Run the frozen 2,000 x 1,000 selector sanity check after development."""

    lower_bounds: list[float] = []
    for t in range(2_000):
        observations = tuple(
            sanity_normal_observation(sigma_plan, n=n, t=t, j=j)
            for j in range(n)
        )
        means = tuple(
            sanity_bootstrap_replicate_mean(observations, t=t, r=r)
            for r in range(1_000)
        )
        lower_bounds.append(sanity_inner_lower_bound(means))
    return sanity_acceptance_fraction(tuple(lower_bounds))


def confirmatory_bootstrap_integer_sum(
    d2_values: tuple[int, ...], *, r: int
) -> int:
    """Compute one exact integer bootstrap statistic for 48 or 64 conversations."""

    n = len(d2_values)
    if n not in {48, 64}:
        raise ValueError("confirmatory values must contain 48 or 64 conversations")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value not in {-2, -1, 0, 1, 2}
        for value in d2_values
    ):
        raise ValueError("confirmatory d2 values must be integers in {-2,-1,0,1,2}")
    return sum(
        d2_values[confirmatory_bootstrap_index(n, r, j)] for j in range(n)
    )


def confirmatory_lower_bound_integer_sum(replicate_sums: tuple[int, ...]) -> int:
    """Return the 500th smallest of exactly 10,000 integer sums."""

    if len(replicate_sums) != 10_000:
        raise ValueError("confirmatory bootstrap requires exactly 10,000 sums")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in replicate_sums):
        raise ValueError("confirmatory replicate sums must be integers")
    return sorted(replicate_sums)[499]


def confirmatory_margin_passes(selected_integer_sum: int, n: int) -> bool:
    """Apply the exact strict bound comparison: 10 * selected sum > n."""

    if n not in {48, 64}:
        raise ValueError("n must be 48 or 64")
    if isinstance(selected_integer_sum, bool) or not isinstance(selected_integer_sum, int):
        raise ValueError("selected integer sum must be an integer")
    return 10 * selected_integer_sum > n


@dataclass(frozen=True, slots=True)
class PowerResult:
    n: int
    sigma_plan: float
    z: float
    power: float
    eligible: bool


def analytic_power(s: float, n: int) -> PowerResult:
    """The sole normative Python 3.13 operation order from the manifest."""

    if n not in {48, 64}:
        raise ValueError("n must be 48 or 64")
    if not isinstance(s, (int, float)) or isinstance(s, bool):
        raise TypeError("s must be numeric")
    s = float(s)
    if not math.isfinite(s) or s < 0:
        raise DeterminismIntegrityError("s must be finite and non-negative")
    sigma_plan = max(0.10, s * math.sqrt(15 / 7.260943927670032))
    z = 0.05 * math.sqrt(n) / sigma_plan - 1.644853626951
    power = statistics.NormalDist().cdf(z)
    eligible = power >= 0.80
    if not all(math.isfinite(value) for value in (sigma_plan, z, power)):
        raise DeterminismIntegrityError("power calculation produced a non-finite value")
    return PowerResult(
        n=n,
        sigma_plan=sigma_plan,
        z=z,
        power=power,
        eligible=eligible,
    )


def select_48_or_stop(s: float, sanity_power: float) -> tuple[int | None, PowerResult]:
    """Apply the frozen 48-conversation selector to supplied sanity power."""

    if (
        isinstance(sanity_power, bool)
        or not isinstance(sanity_power, (int, float))
        or not math.isfinite(sanity_power)
        or not 0.0 <= sanity_power <= 1.0
    ):
        raise DeterminismIntegrityError("sanity power must be a finite probability")
    result = analytic_power(s, 48)
    if result.eligible and float(sanity_power) >= 0.78:
        return 48, result
    return None, result


def run_registered_selector(s: float) -> tuple[int | None, PowerResult, float]:
    """Run the registered 48-only analytic and 2,000 x 1,000 sanity checks."""

    result = analytic_power(s, 48)
    sanity_power = run_registered_local_sanity(result.sigma_plan, 48)
    selected, _ = select_48_or_stop(s, sanity_power)
    return selected, result, sanity_power
