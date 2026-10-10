"""The record of every use of the usage endpoint, and the call rate read from it."""

from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen

CALLS_NAME = "usage-calls.jsonl"


class UsageCall(Frozen):
    """One line of the record: a call to the endpoint, or a reading answered from the cache."""

    at: datetime
    caller: str
    outcome: str  # ok, rate_limited, timeout, error or cache
    status: int | None = None
    latency_ms: int = 0
    headers: dict[str, str] = {}
    age_seconds: int | None = None  # a cached reading's age


class Refusal(Frozen):
    at: datetime
    quiet_seconds: int | None  # since the call before it, None when there was none
    calls_before: int  # calls in the fifteen minutes before it


class CallWindow(Frozen):
    calls: int
    by_outcome: dict[str, int]
    by_caller: dict[str, int]
    cache_share: float
    refusals: tuple[Refusal, ...]


class CallRate(Frozen):
    hour: CallWindow
    day: CallWindow
    last_refusal_at: datetime | None
    safe_interval_seconds: int | None


def read_calls(path: Path) -> list[UsageCall]:
    raise NotImplementedError


def derive_rate(calls: list[UsageCall], *, now: datetime) -> CallRate:
    raise NotImplementedError


def rate_line(rate: CallRate) -> str:
    raise NotImplementedError
