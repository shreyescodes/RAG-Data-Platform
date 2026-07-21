# RAG Financial Platform

[![CI](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/release/python-3100/)
[![Node.js 18+](https://img.shields.io/badge/node-18+-green.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A full-stack synthetic data platform with Retrieval-Augmented Generation (RAG) workflows and advanced multi-agent capabilities for querying financial data using natural language.

## Overview

This platform demonstrates:
- **RAG Workflow**: Semantic retrieval + SQL generation from natural language
- **Multi-Agent System**: Orchestrated agents for retrieval, analysis, and enrichment
- **Financial Data**: 5+ tables with 5000+ rows of financial and portfolio data
- **Vector Search**: FAISS-based semantic search over database schema
- **API Enrichment**: Integration with Yahoo Finance and SEC EDGAR

## Architecture

### Backend (FastAPI)
```
backend/
├── api/          # FastAPI endpoints
├── db/           # Database models and connection
├── rag/          # Vector store, embeddings, SQL generation
├── agents/       # Multi-agent orchestration system
└── utils/        # Data loading utilities
```

### Multi-Agent System

1. **Retrieval Agent**: Semantic search → SQL generation → Query execution
2. **Analysis Agent**: Summarization, insights, and reasoning
3. **Enrichment Agent**: Fetches external data (Yahoo Finance, SEC EDGAR)

### Database Schema

- `companies` - Company information and metadata
- `financial_statements` - Income statements, balance sheets, cash flow (5000+ rows)
- `portfolio_companies` - PE fund portfolio tracking
- `performance_metrics` - ARR, MRR, churn, CAC, LTV (5000+ rows)
- `market_data` - Historical stock prices
- `query_logs` - Query history and debugging

## Setup Instructions

### Prerequisites

- Python 3.10+ with pip
- Node.js 18+ and npm
- PostgreSQL 13+
- Docker & Docker Compose (recommended)

---

### Option A — Docker (Recommended)

**1. Copy the example env file and fill in your values:**

```bash
cp .env.example .env
```

Edit `.env` and set **all** required variables (see [Environment Variables](#environment-variables) below).

**2. Start all services:**

```bash
docker compose up --build
```

- API: `http://localhost:8000`
- Frontend: `http://localhost:5173`

---

### Option B — Local Development

**1. Database Setup**

Create a PostgreSQL database:
```bash
createdb RAG-Data
```

**2. Environment**

```bash
cp .env.example .env
# Edit .env — fill in DATABASE_URL, OPENAI_API_KEY, API_KEY, etc.
```

**3. Backend Setup**

```bash
cd backend
pip install -r requirements.txt
python setup_data.py   # Creates tables, loads data, indexes schema
```

Start the FastAPI server:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**4. Frontend Setup**

```bash
cd frontend
npm install
npm run dev
```

Frontend: `http://localhost:5173`

---

## Environment Variables

Copy `.env.example` to `.env` and fill in every required value. **Never commit `.env`.**

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ Yes | Full PostgreSQL connection string |
| `POSTGRES_USER` | ✅ Yes | Postgres username (Docker) |
| `POSTGRES_PASSWORD` | ✅ Yes | Postgres password (Docker) — use a strong random value |
| `POSTGRES_DB` | ✅ Yes | Postgres database name (Docker) |
| `OPENAI_API_KEY` | ✅ Yes | OpenAI API key for GPT-4 and embeddings |
| `SEC_EDGAR_API_KEY` | Optional | SEC EDGAR API key for filing enrichment |
| `API_KEY` | ✅ Yes (production) | Secret key sent in `X-API-Key` header — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ALLOWED_ORIGINS` | Optional | Comma-separated CORS origins (default: `http://localhost:5173`) |
| `FAISS_INDEX_PATH` | Optional | Path to FAISS index (default: `data/faiss_index`) |
| `API_HOST` | Optional | Bind host (default: `0.0.0.0`) |
| `API_PORT` | Optional | Bind port (default: `8000`) |

> **Note:** `API_KEY` can be left empty to disable authentication in local development. **Always set it in production.**

---

## Usage

### Authenticating API Requests

All endpoints except `/` and `/api/health` require an `X-API-Key` header:

```bash
curl -H "X-API-Key: your_api_key" http://localhost:8000/api/stats
```

When using the frontend, set `VITE_API_URL` and pass the key via the env — the UI handles it automatically if `VITE_API_KEY` is set.

### Example Queries

- "What are the total liabilities in Company X?"
- "What's the YoY revenue growth in 2024?"
- "Show me all portfolio companies with ARR over 1M"
- "What is the average churn rate across all companies?"
- "List companies in the technology sector"
- "What's the current stock price for AAPL?"

### API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET` | `/` | No | API info |
| `GET` | `/api/health` | No | Health check |
| `POST` | `/api/query` | ✅ | Submit natural language query |
| `GET` | `/api/history` | ✅ | View query history (max 100 per page) |
| `GET` | `/api/stats` | ✅ | Platform statistics |
| `POST` | `/api/index-schema` | ✅ | Re-index database schema (admin) |

### Query Response Format

```json
{
  "success": true,
  "query": "What are the total liabilities?",
  "sql": "SELECT SUM(total_liabilities) FROM financial_statements LIMIT 500",
  "answer": "The total liabilities amount to $5.2M",
  "summary": "Query executed successfully...",
  "insights": ["Finding 1", "Finding 2"],
  "data": [],
  "row_count": 10,
  "relevant_tables": ["financial_statements"],
  "enriched_data": {},
  "execution_time_ms": 245.5,
  "agent_flow": {
    "retrieval": "completed",
    "analysis": "completed",
    "enrichment": "skipped"
  }
}
```

---

## Technical Stack

### Backend
- **FastAPI** — Modern async web framework
- **SQLAlchemy 2** — ORM for PostgreSQL
- **Alembic** — Database migrations
- **OpenAI** — GPT-4o-mini for SQL generation and analysis
- **FAISS** — Vector similarity search
- **sqlglot** — SQL parsing and validation
- **slowapi** — Rate limiting
- **Pandas** — Data manipulation
- **yfinance** — Yahoo Finance integration

### Frontend
- **React 19** — UI framework
- **Vite** — Build tool and dev server

### Infrastructure
- **Docker / Docker Compose** — Containerised deployment
- **PostgreSQL 13** — Primary database
- **nginx** — Frontend static server

---

## Security

This project implements the following security controls:

- **API Key authentication** — All data endpoints require `X-API-Key`
- **Restricted CORS** — Origins controlled via `ALLOWED_ORIGINS` env var
- **SQL injection prevention** — LLM-generated SQL is validated (SELECT-only) and row-capped (500) via `sqlglot`
- **Rate limiting** — `/api/query` limited to 20/min per IP; `/api/index-schema` to 5/hour
- **Sanitised error responses** — Internal errors logged server-side; generic messages returned to clients
- **Security response headers** — `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`
- **Non-root Docker user** — Backend container runs as `appuser`
- **No hardcoded secrets** — All credentials must be explicitly provided via environment

---

## Development

### Adding New Data

```python
from backend.utils.data_loader import DataLoader
from backend.db.database import SessionLocal

db = SessionLocal()
loader = DataLoader(db)
loader.synthesize_financial_data(['TSLA', 'NVDA'], num_years=2)
```

### Re-indexing Schema

After database changes (requires API key):
```bash
curl -X POST http://localhost:8000/api/index-schema \
  -H "X-API-Key: your_api_key"
```

---

## Project Structure

```
.
├── backend/
│   ├── api/main.py           # FastAPI application
│   ├── agents/
│   │   ├── retrieval_agent.py
│   │   ├── analysis_agent.py
│   │   ├── enrichment_agent.py
│   │   └── orchestrator.py
│   ├── rag/
│   │   ├── embeddings.py
│   │   ├── vector_store.py
│   │   ├── schema_indexer.py
│   │   └── sql_generator.py
│   ├── db/
│   │   ├── models.py
│   │   └── database.py
│   └── utils/
│       └── data_loader.py
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # React UI
│   │   └── App.css
│   ├── package.json
│   └── vite.config.js
├── .env.example                 # Template — copy to .env and fill in
├── docker-compose.yml
└── README.md
```

---

## Future Improvements

- Add more sophisticated query planning
- Implement query result caching
- Add support for complex joins across 3+ tables
- Implement policy agent for query validation
- Add real-time data streaming
- Support for multi-turn conversations
- Deploy to cloud platform

## License

MIT
