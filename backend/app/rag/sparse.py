"""BM25 keyword retrieval over the schema documents.

Dense embeddings match meaning ("recurring revenue" ~ "ARR") but are weak on
exact identifiers such as `ma_50`, `eps` or `ltv`. BM25 is the complement:
it scores documents by the rarity of the exact terms they share with the query.

The implementation is Okapi BM25 with the Lucene IDF (always non-negative).
The corpus is a few hundred short documents, so a dense in-memory scan is
faster than any inverted index would be and needs no extra dependency.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

_WORD = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")

# Question words and fillers that carry no schema signal.
_STOPWORD_TEXT = """
a an and any are as at be by can did do does each for from give how i in is it its
list me most my of on or over per show tell than that the their them there these this
those to was were what when where which who whose why with
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _stem(token: str) -> str:
    """Tiny plural folder so "companies" matches "company" and "rates" "rate"."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lower-case terms; snake_case identifiers yield both parts and the whole.

    "ma_50 trend" -> ["ma_50", "ma", "50", "trend"], so a query that names a
    column exactly scores higher than one that merely shares a word with it.
    """
    tokens: list[str] = []
    for word in _WORD.findall(text.lower()):
        parts = word.split("_")
        if len(parts) > 1:
            tokens.append(word)
        tokens.extend(_stem(p) for p in parts if p and p not in STOPWORDS)
    return tokens


@dataclass(frozen=True, slots=True)
class SparseHit:
    index: int  # position of the document in the corpus
    score: float  # raw BM25 score, > 0


class BM25Index:
    def __init__(self, corpus: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._docs = [Counter(tokenize(text)) for text in corpus]
        self._lengths = [sum(doc.values()) for doc in self._docs]
        self._avg_length = (sum(self._lengths) / len(self._docs)) if self._docs else 0.0
        frequencies: Counter[str] = Counter()
        for doc in self._docs:
            frequencies.update(doc.keys())
        n = len(self._docs)
        self._idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in frequencies.items()
        }

    @property
    def size(self) -> int:
        return len(self._docs)

    def scores(self, query: str) -> list[float]:
        """BM25 score of every document for `query` (0.0 where no term matches)."""
        terms = [t for t in dict.fromkeys(tokenize(query)) if t in self._idf]
        out = [0.0] * len(self._docs)
        if not terms or not self._avg_length:
            return out
        k1, b = self._k1, self._b
        for i, doc in enumerate(self._docs):
            norm = k1 * (1 - b + b * self._lengths[i] / self._avg_length)
            score = 0.0
            for term in terms:
                tf = doc.get(term, 0)
                if tf:
                    score += self._idf[term] * tf * (k1 + 1) / (tf + norm)
            out[i] = score
        return out

    def search(self, query: str, k: int = 10) -> list[SparseHit]:
        """Top-`k` documents with a positive score, best first (ties by position)."""
        ranked = sorted(
            ((i, s) for i, s in enumerate(self.scores(query)) if s > 0),
            key=lambda pair: (-pair[1], pair[0]),
        )
        return [SparseHit(index=i, score=s) for i, s in ranked[:k]]
