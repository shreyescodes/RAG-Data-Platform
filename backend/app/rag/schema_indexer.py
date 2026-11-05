"""Schema catalog and hybrid table retrieval.

The catalog is derived from the ORM metadata (the same source Alembic
migrations are generated from) so that descriptions in `info["description"]`
travel with the schema. Each table and each column becomes one document.

At query time documents are scored by up to three signals:

1. dense: cosine similarity of sentence embeddings (FAISS), good at meaning;
2. sparse: BM25 over the same texts, good at exact identifiers (`ma_50`);
3. a cross-encoder that rescores the fused shortlist jointly with the query.

Dense and sparse rankings are merged with Reciprocal Rank Fusion. Document
scores are then aggregated per table and expanded along foreign keys so the
SQL generator always sees complete, joinable tables. Every intermediate score
is kept so answers can cite why each table was chosen.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import MetaData, Table

from app.db.models import Base
from app.rag.fusion import DEFAULT_K, max_rrf_score, reciprocal_rank_fusion
from app.rag.reranker import Reranker
from app.rag.sparse import BM25Index
from app.rag.vector_store import Document, FAISSVectorStore, SearchHit

logger = logging.getLogger(__name__)

# How many raw hits each retriever contributes before fusion.
_SEARCH_DEPTH = 30
# Fused documents passed to the cross-encoder.
DEFAULT_RERANK_CANDIDATES = 12
# Bonus per additional matching document, rewarding tables that match broadly.
_BREADTH_BONUS = 0.02
# Tables scoring below this fraction of the best table are treated as noise.
# Each mode scores on its own scale: cosine similarity (dense), RRF normalised
# to [0, 1] (fused) and cross-encoder probability (rerank).
_RELATIVE_CUTOFF = {"dense": 0.75, "fused": 0.5, "rerank": 0.3}
# Candidates echoed into the agent trace.
TRACE_CANDIDATES = 10

RetrievalMode = Literal["dense", "hybrid", "dense+rerank", "hybrid+rerank"]


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    description: str
    references: str | None  # "table.column" for foreign keys
    unique: bool = False


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]
    # Tables joinable without a foreign key, declared via info["related_tables"].
    related: tuple[str, ...] = ()
    # Columns identifying a row without a constraint, via info["natural_key"].
    natural_key: tuple[str, ...] = ()

    def identifies_rows(self, column: str) -> bool:
        """Whether `column` is (part of) a key that identifies rows of this table."""
        return column in self.natural_key or any(
            c.name == column and (c.primary_key or c.unique) for c in self.columns
        )

    @property
    def referenced_tables(self) -> frozenset[str]:
        """Tables this one joins to: foreign-key parents plus declared relations."""
        parents = {c.references.split(".", 1)[0] for c in self.columns if c.references}
        return frozenset(parents | set(self.related))

    def to_ddl(self) -> str:
        """Render as annotated DDL, the format LLMs translate to SQL most reliably."""
        lines = [f"-- {self.description}"] if self.description else []
        lines.append(f"CREATE TABLE {self.name} (")
        col_lines = []
        for col in self.columns:
            parts = [f"  {col.name} {col.type}"]
            if col.primary_key:
                parts.append("PRIMARY KEY")
            elif not col.nullable:
                parts.append("NOT NULL")
            if col.references:
                parts.append(f"REFERENCES {col.references}")
            line = " ".join(parts)
            if col.description:
                line += f"  -- {col.description}"
            col_lines.append(line)
        lines.append(",\n".join(col_lines))
        lines.append(");")
        return "\n".join(lines)


def _table_info(table: Table) -> TableInfo:
    columns = []
    for col in table.columns:
        fk = next(iter(col.foreign_keys), None)
        columns.append(
            ColumnInfo(
                name=col.name,
                type=str(col.type),
                nullable=bool(col.nullable),
                primary_key=bool(col.primary_key),
                description=str(col.info.get("description", "")),
                references=fk.target_fullname if fk is not None else None,
                unique=bool(col.unique),
            )
        )
    return TableInfo(
        name=table.name,
        description=str(table.info.get("description", "")),
        columns=tuple(columns),
        related=tuple(table.info.get("related_tables", ())),
        natural_key=tuple(table.info.get("natural_key", ())),
    )


def build_schema_catalog(metadata: MetaData = Base.metadata) -> dict[str, TableInfo]:
    """Return the tables the LLM is allowed to see, keyed by name."""
    return {
        table.name: _table_info(table)
        for table in metadata.sorted_tables
        if table.info.get("queryable", True)
    }


def _documents_for(table: TableInfo) -> Iterable[tuple[str, Document]]:
    column_list = ", ".join(c.name for c in table.columns)
    yield (
        f"Table {table.name}: {table.description} Columns: {column_list}.",
        {"kind": "table", "table": table.name},
    )
    for col in table.columns:
        text = f"Column {table.name}.{col.name} ({col.type})"
        if col.description:
            text += f": {col.description}"
        if table.description:
            text += f" Part of {table.name}: {table.description}"
        yield text, {"kind": "column", "table": table.name, "column": col.name}


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 4)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """One schema document and every score it received."""

    document: str  # "table" or "table.column"
    table: str
    kind: str
    final_score: float
    final_rank: int
    dense_score: float | None = None
    dense_rank: int | None = None
    sparse_score: float | None = None
    sparse_rank: int | None = None
    fused_score: float | None = None  # RRF score normalised to [0, 1]
    fused_rank: int | None = None
    rerank_score: float | None = None  # cross-encoder probability in [0, 1]

    def as_dict(self) -> dict[str, Any]:
        return {
            "document": self.document,
            "kind": self.kind,
            "dense_score": _round(self.dense_score),
            "dense_rank": self.dense_rank,
            "sparse_score": _round(self.sparse_score),
            "sparse_rank": self.sparse_rank,
            "fused_score": _round(self.fused_score),
            "fused_rank": self.fused_rank,
            "rerank_score": _round(self.rerank_score),
            "final_rank": self.final_rank,
        }


@dataclass(frozen=True, slots=True)
class TableScore:
    """Why a table was handed to the SQL generator."""

    table: str
    rank: int
    via: Literal["retrieved", "foreign_key"]
    score: float | None  # final score of the table's best document
    best_document: str | None
    matched_columns: tuple[str, ...]
    dense_score: float | None = None
    sparse_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "table": self.table,
            "rank": self.rank,
            "via": self.via,
            "score": _round(self.score),
            "best_document": self.best_document,
            "matched_columns": list(self.matched_columns),
            "dense_score": _round(self.dense_score),
            "sparse_score": _round(self.sparse_score),
            "fused_score": _round(self.fused_score),
            "rerank_score": _round(self.rerank_score),
        }


@dataclass(slots=True)
class SchemaSearchResult:
    mode: RetrievalMode
    tables: list[TableInfo] = field(default_factory=list)
    table_scores: list[TableScore] = field(default_factory=list)
    candidates: list[CandidateScore] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    # Set when a stage failed and retrieval fell back (e.g. reranker missing).
    degraded: str | None = None

    @property
    def table_names(self) -> list[str]:
        return [t.name for t in self.tables]

    @property
    def confidence(self) -> float | None:
        """Cross-encoder probability of the best table, when reranking ran."""
        scores = [s.rerank_score for s in self.table_scores if s.rerank_score is not None]
        return max(scores) if scores else None

    def trace_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "tables": self.table_names,
            "mode": self.mode,
            "table_scores": [s.as_dict() for s in self.table_scores],
            "candidates": [c.as_dict() for c in self.candidates[:TRACE_CANDIDATES]],
            "timings_ms": self.timings_ms,
        }
        if self.degraded:
            detail["degraded"] = self.degraded
        return detail


def _label(doc: Document) -> str:
    table = str(doc.get("table", ""))
    column = doc.get("column")
    return f"{table}.{column}" if column else table


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class SchemaIndexer:
    def __init__(
        self,
        vector_store: FAISSVectorStore,
        catalog: dict[str, TableInfo] | None = None,
        *,
        hybrid: bool = False,
        reranker: Reranker | None = None,
        rrf_k: int = DEFAULT_K,
        rerank_candidates: int = DEFAULT_RERANK_CANDIDATES,
    ) -> None:
        self._store = vector_store
        self.catalog = catalog if catalog is not None else build_schema_catalog()
        self.hybrid = hybrid
        self.reranker = reranker
        self._rrf_k = rrf_k
        self._rerank_candidates = rerank_candidates
        self._sparse: tuple[int, BM25Index] | None = None
        self._sparse_lock = threading.Lock()

    @property
    def mode(self) -> RetrievalMode:
        if self.hybrid:
            return "hybrid+rerank" if self.reranker is not None else "hybrid"
        return "dense+rerank" if self.reranker is not None else "dense"

    def index(self) -> int:
        """(Re)build the vector index from the catalog. Returns document count.

        The BM25 index is derived from the same documents and rebuilds lazily.
        """
        pairs = [pair for table in self.catalog.values() for pair in _documents_for(table)]
        texts = [text for text, _ in pairs]
        documents = [{**doc, "text": text} for text, doc in pairs]
        return self._store.rebuild(texts, documents)

    def find_relevant_tables(self, query: str, max_tables: int) -> list[TableInfo]:
        """Tables to show the SQL generator for `query`, best first."""
        return self.search(query, max_tables).tables

    def search(self, query: str, max_tables: int) -> SchemaSearchResult:
        """Rank tables for `query`, keeping every score that led there."""
        result = SchemaSearchResult(mode=self.mode)
        generation, documents = self._store.snapshot()

        started = time.perf_counter()
        dense_hits = self._store.search(query, k=_SEARCH_DEPTH)
        result.timings_ms["dense"] = _ms_since(started)
        if not dense_hits:
            return result
        if not self.hybrid and self.reranker is None:
            return self._dense_only(result, dense_hits, max_tables)

        dense = {h.index: (rank, h.score) for rank, h in enumerate(dense_hits, start=1)}
        sparse: dict[int, tuple[int, float]] = {}
        fused: dict[int, tuple[int, float]] = {}
        order = list(dense)
        if self.hybrid:
            started = time.perf_counter()
            bm25 = self._sparse_index(generation, documents)
            sparse_hits = bm25.search(query, k=_SEARCH_DEPTH)
            sparse = {h.index: (rank, h.score) for rank, h in enumerate(sparse_hits, start=1)}
            result.timings_ms["sparse"] = _ms_since(started)
            fused_ranking = reciprocal_rank_fusion(
                {"dense": list(dense), "sparse": list(sparse)}, k=self._rrf_k
            )
            norm = max_rrf_score(2, k=self._rrf_k)
            fused = {i: (rank, s / norm) for rank, (i, s) in enumerate(fused_ranking, start=1)}
            order = [i for i, _ in fused_ranking]

        pool = order[: self._rerank_candidates]
        rerank: dict[int, float] = {}
        if self.reranker is not None:
            started = time.perf_counter()
            try:
                scores = self.reranker.score(query, [str(documents[i]["text"]) for i in pool])
                rerank = dict(zip(pool, scores, strict=True))
            except Exception as exc:  # an enhancement, never a hard dependency
                logger.warning("Reranker unavailable; using fused ranking: %r", exc)
                result.degraded = f"reranker unavailable ({type(exc).__name__})"
            result.timings_ms["rerank"] = _ms_since(started)

        def final(i: int) -> float:
            if rerank:
                return rerank[i]
            return fused[i][1] if fused else dense[i][1]

        position = {i: n for n, i in enumerate(pool)}
        ranked = sorted(pool, key=lambda i: (-final(i), position[i]))
        for final_rank, i in enumerate(ranked, start=1):
            doc = documents[i]
            d, sp, f = dense.get(i), sparse.get(i), fused.get(i)
            result.candidates.append(
                CandidateScore(
                    document=_label(doc),
                    table=str(doc.get("table", "")),
                    kind=str(doc.get("kind", "")),
                    final_score=final(i),
                    final_rank=final_rank,
                    dense_score=d[1] if d else None,
                    dense_rank=d[0] if d else None,
                    sparse_score=sp[1] if sp else None,
                    sparse_rank=sp[0] if sp else None,
                    fused_score=f[1] if f else None,
                    fused_rank=f[0] if f else None,
                    rerank_score=rerank.get(i),
                )
            )

        scale = "rerank" if rerank else ("fused" if fused else "dense")
        return self._select_tables(
            result, max_tables, _RELATIVE_CUTOFF[scale], strong_matches_only=True
        )

    # -- table selection ---------------------------------------------------------
    def _dense_only(
        self, result: SchemaSearchResult, hits: Sequence[SearchHit], max_tables: int
    ) -> SchemaSearchResult:
        result.candidates = [
            CandidateScore(
                document=_label(hit.document),
                table=str(hit.document.get("table", "")),
                kind=str(hit.document.get("kind", "")),
                final_score=hit.score,
                final_rank=rank,
                dense_score=hit.score,
                dense_rank=rank,
            )
            for rank, hit in enumerate(hits, start=1)
        ]
        return self._select_tables(result, max_tables, _RELATIVE_CUTOFF["dense"])

    def _select_tables(
        self,
        result: SchemaSearchResult,
        max_tables: int,
        relative_cutoff: float,
        *,
        strong_matches_only: bool = False,
    ) -> SchemaSearchResult:
        """Aggregate documents to tables, drop weak tables, expand joins.

        The breadth bonus rewards tables matching on several documents. With
        `strong_matches_only` only documents above the cutoff count, so wide
        tables cannot outrank a table with one decisive match on volume alone.
        """
        candidates = [c for c in result.candidates if c.table in self.catalog]
        if not candidates:
            return result
        top = max(c.final_score for c in candidates)
        cutoff = top * relative_cutoff if top > 0 else top

        best: dict[str, CandidateScore] = {}
        count: defaultdict[str, int] = defaultdict(int)
        columns: defaultdict[str, list[str]] = defaultdict(list)
        for cand in candidates:
            if cand.table not in best or cand.final_score > best[cand.table].final_score:
                best[cand.table] = cand
            if strong_matches_only and cand.final_score < cutoff:
                continue
            count[cand.table] += 1
            if cand.kind == "column":
                columns[cand.table].append(cand.document.split(".", 1)[1])

        ranked = sorted(
            (t for t in best if best[t].final_score >= cutoff),
            key=lambda t: best[t].final_score + _BREADTH_BONUS * max(count[t] - 1, 0),
            reverse=True,
        )[:max_tables]
        expanded = self._expand_foreign_keys(ranked)

        result.tables = [self.catalog[name] for name in expanded]
        for rank, name in enumerate(expanded, start=1):
            hit = best.get(name)
            result.table_scores.append(
                TableScore(
                    table=name,
                    rank=rank,
                    via="retrieved" if name in ranked else "foreign_key",
                    score=hit.final_score if hit else None,
                    best_document=hit.document if hit else None,
                    # Columns in final-rank order, at most a handful for display.
                    matched_columns=tuple(columns.get(name, ())[:5]),
                    dense_score=hit.dense_score if hit else None,
                    sparse_score=hit.sparse_score if hit else None,
                    fused_score=hit.fused_score if hit else None,
                    rerank_score=hit.rerank_score if hit else None,
                )
            )
        return result

    def _expand_foreign_keys(self, tables: Sequence[str]) -> list[str]:
        ordered = list(tables)
        seen = set(ordered)
        i = 0
        while i < len(ordered):
            for parent in sorted(self.catalog[ordered[i]].referenced_tables):
                if parent in self.catalog and parent not in seen:
                    seen.add(parent)
                    ordered.append(parent)
            i += 1
        return ordered

    def _sparse_index(self, generation: int, documents: Sequence[Document]) -> BM25Index:
        with self._sparse_lock:
            if self._sparse is None or self._sparse[0] != generation:
                self._sparse = (generation, BM25Index([str(d.get("text", "")) for d in documents]))
            return self._sparse[1]
