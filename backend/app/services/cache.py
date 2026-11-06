"""Response caches in front of the LLM.

Two layers, both in-process, bounded (LRU) and expiring (TTL):

- `ResponseCache`: exact match on everything that shapes a completion (model,
  prompts, decoding settings). It only ever stores replies that already passed
  schema validation, so an invalid reply is never replayed.
- `SemanticCache`: reuses generated SQL for *similar* questions over the same
  schema context. Similar means a high embedding similarity **and** identical
  guard terms (numbers, names, tickers, quoted values, ordering and negation
  words), because "top 5" vs "top 10" or "highest" vs "lowest" embed almost
  identically but need different SQL. Cached SQL is re-validated and re-run, so
  results always reflect current data.

Each API process holds its own caches; they warm up independently.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

import numpy as np

from app.rag.embeddings import Embedder

V = TypeVar("V")

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_QUOTED = re.compile(r"[\"'“‘]([^\"'”’]+)[\"'”’]")
_CAPITALISED = re.compile(r"\b[A-Z][A-Za-z0-9&.-]*\b")
# Words that flip or scope a query's meaning while barely moving its embedding.
_CONTRAST_TEXT = """
    highest lowest most least top bottom max maximum min minimum largest smallest biggest
    best worst first last latest earliest oldest newest increase increased decrease
    decreased growth decline above below over under more less greater fewer before after
    ascending descending asc desc not no without except exclude excluding only average
    total sum count median annual annually quarterly monthly daily weekly yearly per
"""
_CONTRAST = frozenset(_CONTRAST_TEXT.split())
_WORD = re.compile(r"[a-z]+")


def stable_key(*parts: Any) -> str:
    """A collision-resistant key for any JSON-serialisable parts."""
    payload = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def guard_terms(question: str) -> frozenset[str]:
    """Terms two questions must share for one's SQL to answer the other."""
    terms = {f"#{n.replace(',', '')}" for n in _NUMBER.findall(question)}
    terms |= {f'"{q.strip().lower()}"' for q in _QUOTED.findall(question)}
    words = question.split()
    for match in _CAPITALISED.finditer(question):
        # Skip the capital that merely starts the sentence ("Which", "Show").
        if match.start() == 0 and not match.group(0).isupper():
            continue
        terms.add(match.group(0).lower())
    terms |= {w for w in _WORD.findall(question.lower()) if w in _CONTRAST}
    if words and words[0].isupper() and len(words[0]) > 1:
        terms.add(words[0].lower())  # a ticker can open the question
    return frozenset(terms)


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    entries: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "entries": self.entries}


class _LRU(Generic[V]):
    def __init__(self, max_entries: int, ttl_seconds: float, clock: Callable[[], float]) -> None:
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self._clock = clock

    def get(self, key: str) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        stored, value = item
        if self._clock() - stored > self._ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: V) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def values(self) -> list[tuple[str, V]]:
        now = self._clock()
        return [(k, v) for k, (t, v) in self._data.items() if now - t <= self._ttl]

    def __len__(self) -> int:
        return len(self._data)


class ResponseCache:
    """Exact-match cache of validated LLM replies."""

    def __init__(
        self,
        *,
        max_entries: int = 1_000,
        ttl_seconds: float = 3_600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lru: _LRU[str] = _LRU(max_entries, ttl_seconds, clock)
        self._lock = threading.Lock()
        self._stats = CacheStats()

    def get(self, key: str) -> str | None:
        with self._lock:
            value = self._lru.get(key)
            if value is None:
                self._stats.misses += 1
            else:
                self._stats.hits += 1
            return value

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._lru.put(key, value)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._stats.hits, self._stats.misses, len(self._lru))


@dataclass(frozen=True, slots=True)
class _SemanticEntry:
    namespace: str
    guards: frozenset[str]
    vector: np.ndarray[Any, np.dtype[np.float32]]
    question: str
    value: str


@dataclass(frozen=True, slots=True)
class SemanticHit:
    value: str
    question: str  # the cached question that matched
    similarity: float


class SemanticCache:
    """Similar-question cache, scoped by a namespace (the schema context)."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        threshold: float = 0.92,
        max_entries: int = 1_000,
        ttl_seconds: float = 3_600,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._embedder = embedder
        self.threshold = threshold
        self._lru: _LRU[_SemanticEntry] = _LRU(max_entries, ttl_seconds, clock)
        self._lock = threading.Lock()
        self._stats = CacheStats()

    def _vector(self, question: str) -> np.ndarray[Any, np.dtype[np.float32]]:
        return np.asarray(self._embedder.encode([question])[0], dtype=np.float32)

    def lookup(self, namespace: str, question: str) -> SemanticHit | None:
        guards = guard_terms(question)
        with self._lock:
            candidates = [
                e for _, e in self._lru.values() if e.namespace == namespace and e.guards == guards
            ]
        best: SemanticHit | None = None
        if candidates:
            query = self._vector(question)
            for entry in candidates:
                similarity = float(np.dot(query, entry.vector))
                if similarity >= self.threshold and (best is None or similarity > best.similarity):
                    best = SemanticHit(entry.value, entry.question, round(similarity, 4))
        with self._lock:
            if best is None:
                self._stats.misses += 1
            else:
                self._stats.hits += 1
        return best

    def store(self, namespace: str, question: str, value: str) -> None:
        entry = _SemanticEntry(
            namespace=namespace,
            guards=guard_terms(question),
            vector=self._vector(question),
            question=question,
            value=value,
        )
        with self._lock:
            self._lru.put(stable_key(namespace, question), entry)

    def stats(self) -> CacheStats:
        with self._lock:
            return CacheStats(self._stats.hits, self._stats.misses, len(self._lru))


def describe(caches: Mapping[str, ResponseCache | SemanticCache | None]) -> dict[str, Any]:
    """Cache status for health output."""
    return {
        name: ({"enabled": True, **cache.stats().as_dict()} if cache else {"enabled": False})
        for name, cache in caches.items()
    }


def schema_namespace(*parts: str | Sequence[str]) -> str:
    """Namespace for cached SQL: changes whenever the schema context does."""
    return stable_key(*parts)[:16]
