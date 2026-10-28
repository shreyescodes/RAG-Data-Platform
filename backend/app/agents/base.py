"""Shared agent primitives: the per-request reasoning trace."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class TraceEntry:
    agent: str
    step: str
    detail: Any
    timestamp: dt.datetime


@dataclass(slots=True)
class Trace:
    """Ordered log of what each agent did while answering one query.

    It is returned to the client for explainability and persisted with the
    query log, so it is created per request and never shared.
    """

    entries: list[TraceEntry] = field(default_factory=list)

    def record(self, agent: str, step: str, detail: Any = None) -> None:
        self.entries.append(
            TraceEntry(agent=agent, step=step, detail=detail, timestamp=dt.datetime.now(dt.UTC))
        )

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "agent": e.agent,
                "step": e.step,
                "detail": e.detail,
                "timestamp": e.timestamp.isoformat(),
            }
            for e in self.entries
        ]


class Agent:
    """Base class giving each agent a stable name for its trace entries."""

    name: ClassVar[str] = "agent"

    def _record(self, trace: Trace, step: str, detail: Any = None) -> None:
        trace.record(self.name, step, detail)
