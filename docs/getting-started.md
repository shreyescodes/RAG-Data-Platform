# Getting started

[← Back to the README](../README.md)

Run the platform with Docker or for local development, and configure it.

## Quick start (Docker)

Prerequisites: Docker with Compose v2 and an LLM API key (a free
[Groq](https://console.groq.com) key works).

```bash
cp .env.example .env
# Edit .env and set at least LLM_API_KEY, API_KEY and POSTGRES_PASSWORD

docker compose up -d --build
docker compose exec backend python -m app.cli seed   # ~10 minutes; downloads Yahoo Finance and SEC data
```

Open <http://localhost:8080>. The nginx container serves the UI and proxies
`/api` to the backend, attaching the API key server-side so it never reaches
the browser. The **Observability** tab shows usage, cost and latency.

### With a local LLM instead of an API key

```bash
# in .env: LLM_BASE_URL=http://ollama:11434/v1, LLM_MODEL=qwen2.5:7b,
#          OLLAMA_MODEL=qwen2.5:7b, LLM_STRUCTURED_OUTPUT=json_schema
docker compose --profile ollama up -d --build      # NVIDIA GPU (ollama-cpu without one)
docker compose exec backend python -m app.cli seed
```

vLLM and llama.cpp profiles, recommended models per GPU size and the health
check are in [docs/PRODUCTION_UPGRADES.md](PRODUCTION_UPGRADES.md#5-local-llm-on-your-own-gpu).

## Local development

Prerequisites: Python 3.11+, Node 20.19+, and a PostgreSQL database.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only build, much smaller
pip install -r requirements-dev.txt
cp ../.env.example ../.env      # set DATABASE_URL and LLM_API_KEY
alembic upgrade head
python -m app.cli seed          # real data from Yahoo Finance and SEC EDGAR (~10 min)
uvicorn app.main:app --reload   # http://localhost:8000/docs

# Frontend (second terminal)
cd frontend
npm ci
npm run dev                     # http://localhost:5173
```

The Vite dev server proxies `/api` to `localhost:8000` and adds `X-API-Key`
from `API_KEY` in the root `.env`. `make help` lists shortcuts for all of the
above.

### Data

Every row is real, public data. `python -m app.cli seed` loads:

| Table | Source | Typical size |
|-------|--------|--------------|
| `companies` | Yahoo Finance: 50 of the largest US-listed companies across all sectors | 50 |
| `market_data` | Yahoo Finance daily OHLCV with 50/200-day moving averages, 2 years | ~25,000 |
| `financial_statements` | Yahoo Finance quarterly and annual statements | ~450 |
| `funds` | SEC EDGAR: 10 well-known 13F filers (Berkshire Hathaway, Bridgewater, ARK, Pershing Square, Duquesne, Soros, Tiger Global, Third Point, Appaloosa, Baupost) | 10 |
| `fund_holdings` | SEC Form 13F: each fund's quarter-end positions for the last 8 quarters, with shares, value and portfolio weight | ~12,000 |

13F filings identify securities by CUSIP. The loader maps them to tickers with
[OpenFIGI](https://www.openfigi.com/api), including CINS codes for
foreign-incorporated issuers, so holdings join to `companies` and
`market_data`. It also detects filers that still report values in thousands of
dollars. `python -m app.cli refresh` adds new prices, statements and filings
and skips what is already stored; the production setup runs it every weekday after the
US close. Run `python -m app.cli seed --help` for options, including `--excel`
to import your own workbook.

## Configuration

All settings are environment variables, validated at startup by
[`app/core/config.py`](../backend/app/core/config.py). The most important:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | *(required)* | SQLAlchemy URL, e.g. `postgresql://user:pass@host:5432/db` |
| `QUERY_DATABASE_URL` | `DATABASE_URL` | Connection for generated SQL, ideally a SELECT-only role |
| `LLM_API_KEY` | empty | Key for a hosted endpoint (`GROQ_API_KEY` also accepted); not needed for local servers |
| `LLM_BASE_URL` / `LLM_MODEL` | Groq / `openai/gpt-oss-120b` | Point at OpenAI, Together, or Ollama / vLLM / llama.cpp on your GPU |
| `LLM_STRUCTURED_OUTPUT` | `json_object` | `json_schema` (constrained decoding, best locally), `json_object` or `prompt` |
| `LLM_STRUCTURED_MAX_ATTEMPTS` | `3` | Attempts per structured reply; errors are fed back on each retry |
| `RETRIEVAL_HYBRID` / `RETRIEVAL_RERANK` | `true` / `true` | BM25 + RRF fusion / cross-encoder reranking |
| `VERIFICATION_MODE` | `hybrid` | Fact check: `off`, `heuristic` (no LLM call) or `hybrid` (adds an LLM judge) |
| `LLM_CACHE_ENABLED` / `SEMANTIC_CACHE_ENABLED` | `true` / `true` | Exact reply cache / similar-question SQL cache |
| `LLM_PRICING` | Groq price for the default model | JSON price table, USD per 1M tokens, for the cost dashboard |
| `API_KEY` | empty | Required `X-API-Key` value; mandatory when `ENVIRONMENT=production` |
| `ENVIRONMENT` | `development` | `production` enforces auth and rejects wildcard CORS |
| `MAX_RESULT_ROWS` | `500` | Hard cap applied to every generated query |
| `SQL_STATEMENT_TIMEOUT_MS` | `15000` | PostgreSQL statement timeout for generated SQL |
| `RATE_LIMIT_QUERY` | `20/minute` | Per-IP limit on `POST /api/query` |
| `ENRICHMENT_ENABLED` | `true` | Toggle Yahoo Finance and SEC EDGAR lookups |

See [`.env.example`](../.env.example) for the full list.

## Project layout

```text
backend/
  app/
    main.py            # application factory, middleware, lifespan
    container.py       # process-wide services (vector store, LLM, HTTP clients)
    cli.py             # seed / index-schema commands
    api/               # routers and dependency wiring
    agents/            # retrieval, enrichment, analysis, verification agents + orchestrator
    rag/               # embeddings, FAISS + BM25 + RRF + reranker, schema catalog,
                       # citations, SQL generator/validator
    services/          # LLM client, structured output, caches, Yahoo Finance, SEC EDGAR
    observability/     # per-request metrics, pricing, aggregation for the dashboard
    db/                # models, sessions, repositories, read-only executor
    ingestion/         # Yahoo Finance and SEC 13F loaders, Excel import
    core/              # config, logging, security, exceptions, rate limiting
    utils/             # PII redaction
  alembic/             # migrations
  eval/                # live, retrieval and hallucination evaluations
  tests/               # unit/ and integration/
frontend/
  src/                 # components/, hooks/, api/, utils/
  nginx/               # production server config
docs/                  # architecture, security, evaluation report, screenshots
```
