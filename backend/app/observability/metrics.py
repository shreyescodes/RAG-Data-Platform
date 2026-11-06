"""Per-request telemetry: stage latencies and LLM usage.

`track_request()` installs a `RequestMetrics` collector in a context variable
for the duration of one query. Code anywhere below it, including the LLM
client and work run in the thread pool (which copies the context), reports
into it with `stage(...)` and `record_llm_call(...)` without any plumbing.
Outside a tracked request both are no-ops.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

# Stages reported in the latency breakdown, in pipeline order.
STAGES = (
    "retrieval",
    "sql_generation",
    "sql_execution",
    "enrichment",
    "analysis",
    "verification",
)


@dataclass(frozen=True, slots=True)
class LLMCallRecord:
    purpose: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    success: bool = True
    cached: bool = False
    # True when the server reported no usage and tokens were estimated.
    estimated: bool = False


@dataclass(slots=True)
class RequestMetrics:
    started: float = field(default_factory=time.perf_counter)
    stages_ms: dict[str, float] = field(default_factory=dict)
    llm_calls: list[LLMCallRecord] = field(default_factory=list)

    def add_stage(self, name: str, ms: float) -> None:
        # Stages can repeat (an SQL repair re-runs generation); time accumulates.
        self.stages_ms[name] = round(self.stages_ms.get(name, 0.0) + ms, 2)

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 2)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.llm_calls if not c.cached)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.llm_calls if not c.cached)

    @property
    def cache_hits(self) -> int:
        return sum(c.cached for c in self.llm_calls)


_current: ContextVar[RequestMetrics | None] = ContextVar("request_metrics", default=None)


def current() -> RequestMetrics | None:
    return _current.get()


@contextmanager
def track_request() -> Iterator[RequestMetrics]:
    metrics = RequestMetrics()
    token = _current.set(metrics)
    try:
        yield metrics
    finally:
        _current.reset(token)


@contextmanager
def stage(name: str) -> Iterator[None]:
    """Time the enclosed block as pipeline stage `name` (no-op when untracked)."""
    started = time.perf_counter()
    try:
        yield
    finally:
        metrics = _current.get()
        if metrics is not None:
            metrics.add_stage(name, (time.perf_counter() - started) * 1000)


def record_llm_call(record: LLMCallRecord) -> None:
    metrics = _current.get()
    if metrics is not None:
        metrics.llm_calls.append(record)


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token) for servers that omit usage."""
    return max(1, round(len(text) / 4))
