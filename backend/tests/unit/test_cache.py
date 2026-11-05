import pytest
from pydantic import BaseModel

from app.observability.metrics import track_request
from app.rag.schema_indexer import build_schema_catalog
from app.rag.sql_generator import SQLGenerator
from app.services.cache import ResponseCache, SemanticCache, describe, guard_terms
from app.services.structured_output import OutputRejected, StructuredOutputExtractor
from tests.fakes import FakeChatModel, HashingEmbedder, sql_reply


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- Guard terms -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("Top 5 companies by revenue", "top 5 companies by revenue?", True),
        ("Top 5 companies by revenue", "Top 10 companies by revenue", False),
        ("Revenue of Apple last quarter", "Revenue of Microsoft last quarter", False),
        ("Which stock had the highest close?", "Which stock had the lowest close?", False),
        ("NVDA closing prices", "AAPL closing prices", False),
        ("Average churn by stage", "Total churn by stage", False),
        ("Companies not in 'Technology'", "Companies in 'Technology'", False),
        ("Show average churn by stage", "List average churn by stage", True),
    ],
)
def test_guard_terms(a: str, b: str, same: bool) -> None:
    assert (guard_terms(a) == guard_terms(b)) is same


# --- Exact cache ---------------------------------------------------------------------------


def test_response_cache_is_lru_with_ttl() -> None:
    clock = Clock()
    cache = ResponseCache(max_entries=2, ttl_seconds=10, clock=clock)
    cache.put("a", "1")
    cache.put("b", "2")
    assert cache.get("a") == "1"  # refreshes "a"
    cache.put("c", "3")  # evicts "b", the least recently used
    assert cache.get("b") is None
    clock.now = 11
    assert cache.get("a") is None  # expired
    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.entries) == (1, 2, 1)  # expired "a" evicted


class Answer(BaseModel):
    text: str


async def test_extractor_replays_validated_replies_only() -> None:
    llm = FakeChatModel(replies={"t": ["not json", '{"text": "ok"}', '{"text": "fresh"}']})
    extractor = StructuredOutputExtractor(llm, cache=ResponseCache())

    first = await extractor.extract(Answer, system="s", user="u", purpose="t")
    assert (first.value.text, first.cached, len(llm.calls)) == ("ok", None, 2)

    with track_request() as metrics:
        second = await extractor.extract(Answer, system="s", user="u", purpose="t")
    assert (second.value.text, second.cached) == ("ok", "exact")
    assert len(llm.calls) == 2  # served from the cache
    assert metrics.cache_hits == 1
    assert metrics.prompt_tokens == 0  # a cache hit bills nothing

    other = await extractor.extract(Answer, system="s", user="different", purpose="t")
    assert other.value.text == "fresh"


async def test_cached_reply_is_revalidated() -> None:
    llm = FakeChatModel(replies={"t": ['{"text": "old"}', '{"text": "new"}']})
    extractor = StructuredOutputExtractor(llm, cache=ResponseCache())
    await extractor.extract(Answer, system="s", user="u", purpose="t")

    def reject_old(value: Answer) -> None:
        if value.text == "old":
            raise OutputRejected("stale")

    result = await extractor.extract(Answer, system="s", user="u", purpose="t", validate=reject_old)
    assert result.value.text == "new"
    assert result.cached is None


# --- Semantic cache -------------------------------------------------------------------------


def test_semantic_cache_needs_similarity_guards_and_namespace() -> None:
    cache = SemanticCache(HashingEmbedder(), threshold=0.8)
    cache.store("ns", "Top 5 companies by revenue", "SQL-5")

    hit = cache.lookup("ns", "top 5 companies by revenue please")
    assert hit is not None
    assert (hit.value, hit.question) == ("SQL-5", "Top 5 companies by revenue")
    assert hit.similarity >= 0.8
    assert cache.lookup("ns", "Top 10 companies by revenue") is None  # guard: number
    assert cache.lookup("other-schema", "Top 5 companies by revenue") is None
    assert cache.lookup("ns", "5 portfolio companies with the most ARR churn") is None
    stats = cache.stats()
    assert (stats.hits, stats.misses, stats.entries) == (1, 3, 1)


def test_describe_reports_disabled_caches() -> None:
    assert describe({"response": ResponseCache(), "semantic": None}) == {
        "response": {"enabled": True, "hits": 0, "misses": 0, "entries": 0},
        "semantic": {"enabled": False},
    }


CATALOG = build_schema_catalog()


def _generator(llm: FakeChatModel, cache: SemanticCache) -> SQLGenerator:
    return SQLGenerator(
        StructuredOutputExtractor(llm),
        max_rows=50,
        allowed_tables=CATALOG.keys(),
        semantic_cache=cache,
    )


async def test_similar_questions_reuse_sql_and_rerun_validation() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies ORDER BY name")
    generator = _generator(llm, SemanticCache(HashingEmbedder(), threshold=0.8))
    tables = [CATALOG["companies"]]

    first = await generator.generate("List all company names", tables)
    second = await generator.generate("list all the company names", tables)

    assert len(llm.calls) == 1
    assert second.cache == "semantic"
    assert second.cache_source == "List all company names"
    assert second.sql == first.sql == "SELECT name FROM companies ORDER BY name LIMIT 50"
    # A different number is a different question.
    await generator.generate("List all company names, 3 of them", tables)
    assert len(llm.calls) == 2


async def test_cached_sql_failing_validation_is_regenerated() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies")
    cache = SemanticCache(HashingEmbedder(), threshold=0.8)
    tables = [CATALOG["companies"]]
    generator = _generator(llm, cache)
    namespace_probe = await generator.generate("List all company names", tables)
    assert namespace_probe.cache is None

    # Poison the entry: the replay must fail the safety validator and regenerate.
    for _, entry in cache._lru.values():
        object.__setattr__(entry, "value", sql_reply("DROP TABLE companies"))
    again = await generator.generate("List all company names", tables)
    assert again.cache is None
    assert again.raw_sql == "SELECT name FROM companies"
    assert len(llm.calls) == 2
