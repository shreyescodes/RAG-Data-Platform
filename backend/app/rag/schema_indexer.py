"""Schema catalog and semantic table retrieval.

The catalog is derived from the ORM metadata (the same source Alembic
migrations are generated from) so that descriptions in `info["description"]`
travel with the schema. Each table and each column becomes one embedded
document; at query time hits are aggregated per table and expanded along
foreign keys so the SQL generator always sees complete, joinable tables.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import MetaData, Table

from app.db.models import Base
from app.rag.vector_store import Document, FAISSVectorStore

# How many raw hits to pull before aggregating to tables.
_SEARCH_DEPTH = 30
# Bonus per additional matching document, rewarding tables that match broadly.
_BREADTH_BONUS = 0.02
# Tables scoring below this fraction of the best match are treated as noise.
_RELATIVE_SCORE_CUTOFF = 0.75


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool
    description: str
    references: str | None  # "table.column" for foreign keys


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    description: str
    columns: tuple[ColumnInfo, ...]
    # Tables joinable without a foreign key, declared via info["related_tables"].
    related: tuple[str, ...] = ()

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
            )
        )
    return TableInfo(
        name=table.name,
        description=str(table.info.get("description", "")),
        columns=tuple(columns),
        related=tuple(table.info.get("related_tables", ())),
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


class SchemaIndexer:
    def __init__(
        self,
        vector_store: FAISSVectorStore,
        catalog: dict[str, TableInfo] | None = None,
    ) -> None:
        self._store = vector_store
        self.catalog = catalog if catalog is not None else build_schema_catalog()

    def index(self) -> int:
        """(Re)build the vector index from the catalog. Returns document count."""
        pairs = [pair for table in self.catalog.values() for pair in _documents_for(table)]
        texts = [text for text, _ in pairs]
        documents = [{**doc, "text": text} for text, doc in pairs]
        return self._store.rebuild(texts, documents)

    def find_relevant_tables(self, query: str, max_tables: int) -> list[TableInfo]:
        """Rank tables by semantic match, then add the tables they join to."""
        hits = self._store.search(query, k=_SEARCH_DEPTH)

        best: dict[str, float] = {}
        count: defaultdict[str, int] = defaultdict(int)
        for hit in hits:
            name = hit.document.get("table")
            if name not in self.catalog:
                continue
            best[name] = max(best.get(name, float("-inf")), hit.score)
            count[name] += 1

        if not best:
            return []
        cutoff = max(best.values()) * _RELATIVE_SCORE_CUTOFF
        ranked = sorted(
            (t for t in best if best[t] >= cutoff),
            key=lambda t: best[t] + _BREADTH_BONUS * (count[t] - 1),
            reverse=True,
        )[:max_tables]
        return [self.catalog[name] for name in self._expand_foreign_keys(ranked)]

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
