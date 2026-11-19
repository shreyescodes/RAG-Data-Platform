# RAG Data Platform

[![CI](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Node 20.19+](https://img.shields.io/badge/node-20.19%2B-green.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

**Ask questions about real financial data in plain English. Get an answer, the
SQL behind it, the source rows and a fact check of every claim.**

[![Read the documentation](https://img.shields.io/badge/Read%20the%20docs-architecture%20%26%20results-2F81F7?style=for-the-badge)](#documentation)

[![One-minute demo: a question over SEC 13F filings with its fact check, sources and SQL, an NVDA price chart, a refused prompt injection, and the observability dashboard](docs/screenshots/demo.webp)](https://drive.google.com/file/d/1Adbpx8WDpOAK_-J5h2qWGv6A2eoaVMOO/view)

<sub>Recorded from a local run of the production Docker stack with real SEC and
Yahoo Finance data. Responses were not mocked or edited. Captions were added and
the wait for the LLM is shortened.</sub>

## How it works

```text
"Which stocks did Berkshire Hathaway buy last quarter?"
        │
        ▼
 PII redaction ─► hybrid schema search ─► structured SQL generation ─► SQL validation ─► read-only execution
                  (FAISS + BM25 + RRF       (JSON schema, retries,       (sqlglot)              │
                   + cross-encoder)          exact/semantic cache)                               │
                                                                                                 ▼
   fact check ◄─ answer + insights ◄─ analysis (LLM) ◄─ enrichment (Yahoo / SEC) ◄─ rows + citations
 (claims vs rows)
```

## What I built

- **Hybrid retrieval:** embeddings and BM25 search, fused and reranked by a
  cross-encoder, to find the right tables for each question.
- **Reliable text-to-SQL:** schema-validated LLM output, with errors fed back
  on retry.
- **SQL safety in depth:** a `sqlglot` allow-list, read-only transactions,
  statement timeouts and row caps.
- **PII redaction:** emails, phone numbers, SSNs, card numbers and IP addresses
  are masked before a question reaches the LLM, logs or audit tables.
- **Hallucination detection:** each claim in an answer is checked against the
  returned rows by rule-based checks and an LLM judge, with evidence shown for
  every verdict.
- **Observability:** tokens, cost, latency per stage and failures for every
  request, on a built-in dashboard.
- **Chat interface:** a React app with recent questions, charts, sources and the
  SQL behind every answer.
- **Production setup:** Docker, automatic TLS, CI and a deploy script that rolls
  back if health checks fail.

## Results

| Measure | Result |
|---|---|
| Execution accuracy against ground-truth SQL | **12/12** |
| Behaviour checks: refusal, live-data fallback, prompt injection, PII, cache | **5/5** |
| Planted hallucinations caught by the rule-based checks | **16/19**, with **0/25** false alarms |
| Questions where search found every table needed | **32/32** |
| Backend tests | **390 passing**, 97% coverage |
| Frontend tests | **86 passing** |

Accuracy was measured on 6 November 2026 with Groq `openai/gpt-oss-120b`, before
the dataset moved to real SEC 13F holdings. The hallucination and retrieval
checks run in CI on every change. [See the full results](docs/results.md).

## Tech stack

| Layer | Tools |
|---|---|
| Backend | Python, FastAPI, Pydantic, SQLAlchemy, Alembic, sqlglot |
| Data | PostgreSQL 16, Yahoo Finance, SEC EDGAR |
| AI and retrieval | sentence-transformers, FAISS, BM25, any OpenAI-compatible LLM |
| Frontend | React 19, Vite |
| Ops | Docker, nginx, Caddy, GitHub Actions |

## Run it locally

You need Docker and an LLM API key. A free [Groq](https://console.groq.com) key
works.

```bash
cp .env.example .env   # set LLM_API_KEY, API_KEY and POSTGRES_PASSWORD
docker compose up -d --build
docker compose exec backend python -m app.cli seed   # about 10 minutes
```

Then open <http://localhost:8080>.

## Documentation

| Topic | What it covers |
|---|---|
| [Features and screenshots](docs/features.md) | Every feature, how it is verified, and screenshots |
| [Architecture](docs/architecture.md) | Pipeline, design decisions, scaling notes and [limitations](docs/architecture.md#limitations) |
| [Measured accuracy](docs/results.md) | Evaluation results and the defects they uncovered |
| [Evaluation reports](docs/evaluation.md) | Full runs: [live](docs/evaluation.md), [local LLM](docs/evaluation-local-llm.md), [retrieval](docs/evaluation-retrieval.md), [hallucination](docs/evaluation-hallucination.md) |
| [Security](docs/security.md) | Threat model and controls |
| [Testing and quality](docs/quality.md) | Test suites and CI checks |
| [Getting started](docs/getting-started.md) | Setup, data, configuration and project layout |
| [API reference](docs/api.md) | Endpoints and response format |
| [Deployment](docs/deployment.md) | Production setup, rollback, backups and monitoring |
| [Production upgrades](docs/PRODUCTION_UPGRADES.md) | How to use and tune each major capability |
| [Contributing](CONTRIBUTING.md) | Workflow and conventions |

## License

[MIT](LICENSE)
