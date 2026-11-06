"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009).

RRF merges ranked lists using ranks only, so retrievers with incomparable
score scales (cosine similarity, BM25) combine without calibration:

    score(d) = sum over lists L containing d of  1 / (k + rank_L(d))

`k` (60 in the paper) damps the influence of any single list's top ranks.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)

DEFAULT_K = 60


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[K]], *, k: int = DEFAULT_K
) -> list[tuple[K, float]]:
    """Fuse best-first rankings into one list of `(key, score)`, best first.

    Ties keep the order in which keys were first seen, which makes the output
    deterministic for a given input.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    scores: dict[K, float] = {}
    for ranking in rankings.values():
        for rank, key in enumerate(dict.fromkeys(ranking), start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: -item[1])


def max_rrf_score(lists: int, *, k: int = DEFAULT_K) -> float:
    """The score of a key ranked first in every one of `lists` rankings."""
    return lists / (k + 1)
