# RAG Financial Platform

[![CI](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml/badge.svg)](https://github.com/shreyescodes/RAG-Data-Platform/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/release/python-3100/)
[![Node.js 18+](https://img.shields.io/badge/node-18+-green.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A full-stack synthetic data platform with Retrieval-Augmented Generation (RAG) workflows, robust security pipelines (PII redaction), and advanced multi-agent orchestration for querying financial data using natural language.

---

## 🎨 Liquid Glass User Interface
The frontend has been completely revamped into a **Bespoke Financial Terminal**, featuring a cutting-edge **Liquid Glass UI**. It embraces a dark, modern aesthetic with deep blurs, high-contrast neon accents, and smooth micro-animations, ensuring zero "AI slop" and providing a premium financial analyst experience.

---

## 🏗️ Architecture & Core Decisions

Recent architectural shifts have transitioned this platform away from paid API dependencies to a highly optimized, cost-effective hybrid model.

### 1. Hybrid LLM & Embedding Strategy
- **Text Generation (Groq):** We leverage the Groq API (using `groq/compound`) for instantaneous SQL generation and agent reasoning. It acts as a drop-in OpenAI API replacement but executes significantly faster and at zero cost.
- **Embeddings (Local Native):** Instead of relying on external services (which cause latency and cost) or heavy local servers (like Ollama), we utilize `sentence-transformers` running directly in the Python process. The vectorizer uses `all-MiniLM-L6-v2` (384 dimensions) for lightning-fast, highly accurate semantic search over the database schema.

### 2. Multi-Agent Pipeline with PII Redaction
We employ a robust orchestrator that sanitizes inputs before routing them to specialized agents.

```mermaid
graph TD
    User([User Query]) --> PII[PII Redactor System]
    PII -- Sanitized Query --> Orchestrator[Agent Orchestrator]
    
    Orchestrator --> |1. Schema & Data Retrieval| RA(Retrieval Agent)
    RA --> |Generates SQL via Groq| DB[(PostgreSQL Data)]
    RA -.-> |FAISS Semantic Search| VS[FAISS Schema Index]
    
    Orchestrator --> |2. Fetch Market Data| EA(Enrichment Agent)
    EA -.-> |yfinance / SEC API| Ext[External APIs]
    
    Orchestrator --> |3. Synthesize Insights| AA(Analysis Agent)
    
    RA --> AA
    EA --> AA
    AA --> |Final Answer & Charts| UI[Liquid Glass Frontend]
```

### 3. PII Reduction System
All inbound user queries pass through the `PIIRedactor`, a strict regex-based sanitization layer that scrubs sensitive entities (Email, Phone, SSN, Credit Cards, IPv4) before they ever touch an LLM or Vector Store.

---

## 🗄️ Database Schema
- `companies` - Company information and metadata
- `financial_statements` - Income statements, balance sheets, cash flow (5000+ rows)
- `portfolio_companies` - PE fund portfolio tracking
- `performance_metrics` - ARR, MRR, churn, CAC, LTV (5000+ rows)
- `market_data` - Historical stock prices
- `query_logs` - Query history and debugging

---

## 🚀 Setup Instructions

### Prerequisites
- Python 3.10+ with pip
- Node.js 18+ and npm
- PostgreSQL 13+
- A free API key from [Groq Console](https://console.groq.com)

### 1. Database Setup
Create a PostgreSQL database:
```bash
createdb rag_data
```

### 2. Environment Variables
Copy `.env.example` to `.env` and fill in every required value. **Never commit `.env`.**

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ Yes | Full PostgreSQL connection string (e.g., `postgresql://postgres:1234@localhost:5432/rag_data`) |
| `GROQ_API_KEY` | ✅ Yes | Groq API Key (e.g. `gsk_...`) |
| `OPENAI_API_KEY` | ✅ Yes | Dummy key (e.g., `"groq"`) for the OpenAI client |
| `OPENAI_API_BASE` | ✅ Yes | Groq Base URL (`https://api.groq.com/openai/v1`) |
| `API_KEY` | Optional | Secret key for auth. Leave blank for local dev. |

### 3. Backend Setup
```bash
cd backend
pip install -r requirements.txt
pip install sentence-transformers  # Required for local embeddings

# Run Alembic migrations to build the tables
alembic upgrade head

# Synthesize mock data (Optional)
python setup_data.py
```
Start the FastAPI server:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Frontend: `http://localhost:5173`

---

## 🔒 Security Posture

This project implements the following security controls:
- **PII Redaction Engine** — All queries are intercepted and sanitized before touching the orchestration layer.
- **Anti-Hallucination Guardrails** — The SQL generator is strictly prompted to refuse queries that require hallucinated tables/columns, returning a clean error rather than breaking the database.
- **SQL Injection Prevention** — LLM-generated SQL is parsed, strictly validated to ensure it is a `SELECT` statement, and row-capped (max 500 rows) via `sqlglot`.
- **Local Embeddings** — FAISS and sentence embeddings run entirely locally. Schema data never leaves the server.
- **Rate Limiting** — API endpoints are protected using `slowapi`.

---

## 🛠️ Technical Stack

### Backend
- **FastAPI** — Modern async web framework
- **SQLAlchemy 2** & **Alembic** — ORM and database migrations
- **Groq API** — Ultra-fast LLM inference (`groq/compound`)
- **Sentence-Transformers** — Local embeddings (`all-MiniLM-L6-v2`)
- **FAISS** — Vector similarity search
- **sqlglot** — SQL parsing and validation

### Frontend
- **React 19** & **Vite** — High-performance UI
- **Vanilla CSS** — Custom Liquid Glass / Bespoke Financial Terminal aesthetics

---

## 📝 License
MIT
