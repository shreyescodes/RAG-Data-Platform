# Production upgrades

Five capabilities were added on top of the original pipeline. Each is on by
default, can be switched off with one environment variable, is covered by
unit and integration tests, and has an evaluation that measures it.

| Capability | Where | Switch | Measured in |
|------------|-------|--------|-------------|
| Hybrid search, reranking, cited answers | `rag/sparse.py`, `rag/fusion.py`, `rag/reranker.py`, `rag/schema_indexer.py`, `rag/citations.py` | `RETRIEVAL_HYBRID`, `RETRIEVAL_RERANK` | [evaluation-retrieval.md](evaluation-retrieval.md) |
| Structured output with validation and retries | `services/structured_output.py`, `rag/sql_generator.py` | `LLM_STRUCTURED_OUTPUT`, `LLM_STRUCTURED_MAX_ATTEMPTS`, `SQL_REPAIR_ATTEMPTS` | unit tests; [evaluation-local-llm.md](evaluation-local-llm.md) |
| Hallucination detector | `agents/verification.py` | `VERIFICATION_MODE` | [evaluation-hallucination.md](evaluation-hallucination.md) |
| Observability dashboard | `observability/`, `api/routes/metrics.py`, `ObservabilityPage.jsx` | always on | integration tests |
| Local LLM on your own GPU, LLM caches | `services/llm.py`, `services/cache.py`, `docker-compose.yml` profiles | `LLM_BASE_URL`, `LLM_CACHE_ENABLED`, `SEMANTIC_CACHE_ENABLED` | [evaluation-local-llm.md](evaluation-local-llm.md) |

Paths are relative to `backend/app/` unless shown otherwise.

**Upgrading an existing deployment:** run `alembic upgrade head` (the Docker
entrypoint does this) to add the `request_metrics` and `llm_calls` tables. No
existing column changes. The API is backward compatible: `QueryResponse`
gains `citations`, `verification` and `usage`, `agent_flow` gains
`verification`, and `/api/health` gains `llm_endpoint` and `llm_configured`.
Nothing was removed or renamed.

---

## 1. Hybrid search, reranking and cited answers

The SQL generator only sees the tables retrieval hands it, so retrieval
decides what can be answered. It now combines three signals:

1. **Dense:** cosine similarity of `all-MiniLM-L6-v2` embeddings (FAISS), as before.
2. **Sparse:** BM25 over the same table and column documents. It catches exact
   identifiers that embeddings blur, such as `ma_50`, `eps` or `runway_months`.
   Snake-case names are indexed both whole and split.
3. **Fusion and reranking:** Reciprocal Rank Fusion (k = 60) merges the two
   rankings by rank alone, so their scores never need calibrating. A local
   cross-encoder (`cross-encoder/ms-marco-MiniLM-L6-v2`, about 90 MB, CPU)
   rescores the fused top 12.

If the reranker cannot load, retrieval falls back to the fused ranking and
marks the trace `degraded`, so it never takes queries down.

**What it bought** (`make eval-retrieval`, 32 questions, real models): with a
budget of one table before join expansion, dense retrieval hands the
generator every table it needs for 28 of 32 questions; hybrid with
reranking does so for 32 of 32. At the production budget of four tables it
is 31/32 vs 32/32, and reranking also sends fewer tables (2.3 vs 2.6 per
prompt). The cost is latency: reranking 12 candidates took about 0.5 s on
the 4-thread laptop CPU used for the evaluation. Set `RETRIEVAL_RERANK=false`
to keep hybrid search at about 30 ms.

**Citations.** Every successful answer carries a `citations` object:

```jsonc
"citations": {
  "retrieval_mode": "hybrid+rerank",
  "retrieval_confidence": 0.93,          // cross-encoder probability of the best table
  "generation_confidence": 0.9,          // the SQL generator's own estimate
  "sql": "SELECT c.name, m.arr FROM ...", // exactly what ran
  "sql_explanation": "Joins each company's latest metrics ...",
  "tables": [{"table": "performance_metrics", "via": "retrieved", "used_in_sql": true,
              "dense_score": 0.61, "sparse_score": 7.4, "fused_score": 1.0,
              "rerank_score": 0.93, "matched_columns": ["arr"]}],
  "columns_referenced": ["companies.name", "performance_metrics.arr", ...],
  "output_columns": [{"output_column": "arr", "sources": ["performance_metrics.arr"],
                      "derivation": "column"}],
  "key_columns": ["name"],              // identify the source row behind each result row
  "aggregated": false,
  "live_sources": [{"kind": "market_data", "ticker": "NVDA", "url": "https://finance.yahoo.com/quote/NVDA"}]
}
```

Column lineage comes from sqlglot, statically, so it costs no query. Row
provenance uses primary keys, unique columns and the natural keys declared
in the models (`info["natural_key"]`, for example `market_data(ticker, date)`);
for grouped results, the group-by columns identify each row. The
**Sources** panel in the UI shows all of it, and the agent trace's
`schema_retrieved` step lists every candidate's dense, sparse, fused and
rerank score and rank.

---

## 2. Structured output with schema validation and retries

`StructuredOutputExtractor.extract(Model, system=..., user=..., purpose=...,
validate=...)` turns any LLM call into a typed, validated value:

- The Pydantic model's JSON Schema is put in the prompt, and the server is
  asked for JSON: `LLM_STRUCTURED_OUTPUT=json_schema` (constrained decoding,
  best for small local models), `json_object` (default) or `prompt`.
- Replies are parsed leniently: code fences, prose around the object and
  `<think>` blocks from reasoning models are stripped.
- Each reply is validated by Pydantic, then by an optional semantic validator
  that raises `OutputRejected`. Any failure is retried, up to
  `LLM_STRUCTURED_MAX_ATTEMPTS` (default 3), with the errors and the rejected
  reply fed back.
- Some servers check JSON mode themselves: Groq answers HTTP 400
  `json_validate_failed` when the model writes broken JSON. The client turns
  that into `InvalidJSONReplyError` carrying the rejected text, and the
  extractor retries it like any other invalid reply instead of treating it as
  an outage. The first Groq run caught this: one rejected reply knocked out
  the claim checker for a whole request.
- After the last attempt it raises `StructuredOutputError`, whose user-facing
  message says the model did not return a valid structured response. The
  trace has one `sql_attempt_rejected` step per failed attempt, with the
  reasons.

To use it for a new step, declare a Pydantic model and call `extract`. Make
every field the code relies on **required**, nullable if it may be empty:
under constrained decoding a model may legally leave out an optional key.
The live evaluation caught exactly this. With `sql` optional, `qwen2.5:1.5b`
omitted it from every reply, identically on every retry; making it required
fixed the problem at the first attempt.

**SQL generation** now returns
`{answerable, sql, explanation, tables_used, confidence}`. The SQL safety
validator runs as the semantic check, so unsafe SQL is fed back with the
reason ("only SELECT queries are allowed"); SQL that keeps failing still
ends as `UnsafeSQLError`, exactly as before. SQL that passes validation but
fails in PostgreSQL (unknown column, type mismatch) is sent back once with
the database error (`SQL_REPAIR_ATTEMPTS`). The **analysis** and
**verification** agents use the same extractor.

---

## 3. Hallucination detector

After the answer is written, `VerificationAgent`:

1. splits the answer, summary and insights into atomic claims (sentences and
   `;` clauses);
2. checks every number, percentage, year, date and named entity in each claim
   against the evidence: the result rows, column aggregates (sum, mean,
   median, min, max, counts), numbers stated in the question, and live market
   data. Percentages match fractions (1.2% to 0.012), and stated precision sets
   the tolerance ($94.0B matches 94,036,000,000). Percentages may also match
   ratios computed from the rows (margins, growth). **A number in a claim
   that names an entity must come from that entity's row**, which catches a
   correct figure attributed to the wrong company. The checks also read the
   way models actually write:
   - dates with month names ("June 30, 2026") and typographic hyphens;
   - ranks and windows ("the top three", "the last 10 days") are not values;
   - a bound on every row ("all five exceed $180M", "volumes stayed above
     26M") is checked against each column of a similar magnitude, so a bound
     that one row breaks is flagged with that row as evidence;
   - in a comparison ("a gap of $92M", "$17.6B higher") a number may be the
     difference of two values;
3. sends claims the checks cannot settle (no checkable facts, a mismatch,
   support only through a computed ratio or difference, or a bound on a
   single row or a total) to one LLM-judge call (`VERIFICATION_MODE=hybrid`).
   The judge also sees the executed SQL, so claims about how rows were chosen
   ("only listed companies", "the highest close") can be checked. The judge
   never overrides a deterministic mismatch.

The response's `verification` lists each claim's verdict (`supported`,
`partially_supported`, `unsupported`, `unverifiable`), reason, confidence and
evidence (`row:3`, `agg:arr.mean`, `market:NVDA`). The **Fact check** panel
shows them; row evidence links to the row in the results table.

**What it catches** (`make eval-hallucination`, 44 labelled claims,
hallucinations planted on purpose): the deterministic checks alone catch
16 of 19 hallucinations with 0 false positives on 25 faithful claims. The 3
misses have no number to check: two qualitative claims ("churn rises sharply
as companies mature") and a sentence-opening invented name. They are marked
unverifiable and sent to the judge. With `qwen2.5:1.5b` as the judge on CPU,
17 of 19 are caught, still with no false positives
([report](evaluation-hallucination.md)). Two cases come from real Groq
answers: bounds, gaps, month-name dates and typographic hyphens that an
earlier version flagged on correct answers.

**On live answers the flag rate is higher than on the labelled set**, because
models add commentary the rows cannot confirm ("the amount is expressed in
billions", "no other ticker was higher"). A flag means "not shown by the
evidence", not "false". See the live numbers in
[evaluation.md](evaluation.md) and read flagged claims with their reasons.

Modes: `off`, `heuristic` (no extra LLM call), `hybrid` (default; the judge
call happens only when some claim needs it).

---

## 4. Observability dashboard

Every query records, in `request_metrics` and `llm_calls`:

- prompt and completion tokens (from the server's usage report, estimated
  when a server omits it), estimated cost, the model, and whether the endpoint
  is local;
- latency for retrieval, SQL generation, SQL execution, enrichment, analysis,
  verification and the total;
- success or the failure type, cache hits, the retrieval mode, and the
  fact-check outcome.

Collection uses a context variable, so no agent signature changed, and a
failure to store metrics never fails the request. The same numbers come back
on each response as `usage`.

| Endpoint (API key required) | Returns |
|----------|---------|
| `GET /api/metrics/summary?window=1h\|6h\|24h\|7d\|30d` | Requests, error rate, tokens, cost, p50/p95/p99 latency overall and per stage, cache hit rate, fact-check flags, usage by model and by step, top failing and most expensive queries |
| `GET /api/metrics/timeseries?window=...` | Requests, failures, tokens, cost and p50/p95 latency per bucket (5 min to 1 day) |
| `GET /api/metrics/recent?limit=50` | The latest requests with stage latencies |

**Cost** uses a price table in USD per million tokens. The built-in table
covers `openai/gpt-oss-120b` on Groq ($0.15 in / $0.60 out); add or override
models with `LLM_PRICING='{"model": {"input": 0.5, "output": 1.5}}'`. A local
endpoint costs $0 unless you price it.

The **Observability** tab in the UI (`/#/observability`) shows KPI tiles,
requests and failures, latency p50/p95, tokens and cost over time,
latency per stage, tokens by step, model usage, failing and expensive
queries, and recent requests. Every chart has a table view and keyboard
navigation.

---

## 5. Local LLM on your own GPU

Any OpenAI-compatible server works. Local endpoints are detected
automatically (loopback, private addresses, Docker service names, `.local`
and `.internal` hosts): they need no API key, cost $0 in the dashboard, and
`/api/health` reports `"llm_endpoint": "local"`.

### Run one with Docker Compose

```bash
# .env
LLM_BASE_URL=http://ollama:11434/v1
LLM_MODEL=qwen2.5:7b
OLLAMA_MODEL=qwen2.5:7b
LLM_STRUCTURED_OUTPUT=json_schema
LLM_TIMEOUT_SECONDS=120

docker compose --profile ollama up -d --build       # NVIDIA GPU
docker compose --profile ollama-cpu up -d --build   # no GPU: small models only
```

The `ollama-pull` helper downloads `OLLAMA_MODEL` on first start. Alternatives:
`--profile vllm` (`LLM_BASE_URL=http://vllm:8000/v1`, `LLM_MODEL` =
`VLLM_SERVED_NAME`) or `--profile llamacpp` (`LLM_BASE_URL=http://llamacpp:8080/v1`).
GPU profiles need the NVIDIA Container Toolkit. Model servers are not
published to the host; only the backend can reach them. For Ollama installed
on the host instead, use `LLM_BASE_URL=http://host.docker.internal:11434/v1`
(the backend service maps that name to the host, Linux included).

These Compose profiles are validated with `docker compose config` but have not
been started on a GPU machine; the self-hosted path was tested with Ollama
running directly on the host.

### Which model

Only `qwen2.5:1.5b` on CPU has been run against this project
([report](evaluation-local-llm.md)). The GPU rows are starting points sized
from the models' download sizes (Q4 quantisation), not measured results:
run `make eval` on your hardware before relying on one.

| GPU memory | Ollama tag | Notes |
|-----------|------------|-------|
| none (CPU) | `qwen2.5:1.5b` | Tested: works end to end, slowly; SQL quality is limited (see below) |
| none (CPU) | `qwen2.5:3b` | Untested; slower, likely better SQL |
| 8 GB | `qwen2.5:7b`, `qwen2.5-coder:7b`, `llama3.1:8b` | ~5 GB at Q4; the coder variant is trained for code and SQL |
| 12-16 GB | `qwen2.5:14b`, `gpt-oss:20b` | ~9 GB and ~14 GB |
| 24 GB | `qwen2.5:32b`, `qwen2.5-coder:32b` | ~20 GB at Q4 |

Use `LLM_STRUCTURED_OUTPUT=json_schema` with local servers: the server
constrains decoding to the schema, so small models return schema-shaped JSON
far more reliably. A reply cut off by `max_tokens` can still be invalid; the
extractor retries those.

A CPU-only model can take one to two minutes per answer. The UI waits up to
5 minutes for a query (`VITE_QUERY_TIMEOUT_MS`, set at build time) and nginx
up to `PROXY_READ_TIMEOUT` (default `300s`); raise `LLM_TIMEOUT_SECONDS` to
match.

### Check it

`GET /api/health/llm` (API key) probes the endpoint and reports whether it is
reachable, its latency, whether the configured model is served, the
structured-output, retrieval and fact-check modes, and cache statistics.

### LLM caches

Two per-process caches (LRU, `LLM_CACHE_TTL_SECONDS`, `LLM_CACHE_MAX_ENTRIES`)
sit in front of the model:

- **Exact** (`LLM_CACHE_ENABLED`): replays a reply for an identical prompt.
  Only replies that passed validation are stored.
- **Semantic** (`SEMANTIC_CACHE_ENABLED`): reuses generated SQL for a similar
  question over the same schema context. A match needs embedding similarity of
  at least `SEMANTIC_CACHE_THRESHOLD` (0.92) **and** the same numbers, names,
  tickers, quoted values and ordering words, because "top 5" and "top 10", or
  "highest" and "lowest", embed almost identically.

Cached SQL is re-validated and re-executed on every hit, so results always
reflect current data. Cache hits appear in `usage`, in the trace
(`"cache": "semantic"` with the question it came from) and on the dashboard.
