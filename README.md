# RAG Financial Platform

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

- Python 3.8+ with pip
- Node.js 16+ and npm
- PostgreSQL 12+

### 1. Database Setup

Create a PostgreSQL database:
```bash
createdb RAG
```

Update `.env` with your database credentials (already configured):
```
DATABASE_URL=postgresql://postgres:1234@localhost:5432/RAG
OPENAI_API_KEY=your_openai_key
SEC_EDGAR_API_KEY=your_sec_edgar_key
```

### 2. Backend Setup

Install Python dependencies:
```bash
cd backend
pip install -r requirements.txt
```

Initialize database and load data:
```bash
python setup_data.py
```

This will:
- Create database tables
- Load Excel data (if available)
- Synthesize financial data from Yahoo Finance for 10 companies
- Generate 5000+ performance metrics
- Index database schema into FAISS vector store

Start the FastAPI server:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

API will be available at: `http://localhost:8000`

### 3. Frontend Setup

Install dependencies and start development server:
```bash
npm install
npm run dev
```

Frontend will be available at: `http://localhost:5173`

## Usage

### Example Queries

The platform can answer questions like:

- "What are the total liabilities in Company X?"
- "What's the YoY revenue growth in 2024?"
- "Show me all portfolio companies with ARR over 1M"
- "What is the average churn rate across all companies?"
- "List companies in the technology sector"
- "What's the current stock price for AAPL?"

### API Endpoints

- `POST /api/query` - Submit natural language query
- `GET /api/history` - View query history
- `GET /api/stats` - Platform statistics
- `GET /api/health` - Health check
- `POST /api/index-schema` - Re-index database schema

### Query Response Format

```json
{
  "success": true,
  "query": "What are the total liabilities?",
  "sql": "SELECT SUM(total_liabilities) FROM financial_statements",
  "answer": "The total liabilities amount to $5.2M",
  "summary": "Query executed successfully...",
  "insights": ["Finding 1", "Finding 2"],
  "data": [...],
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

## Technical Stack

### Backend
- FastAPI - Modern web framework
- SQLAlchemy - ORM for PostgreSQL
- OpenAI - GPT-4 for SQL generation and analysis
- FAISS - Vector similarity search
- Pandas - Data manipulation
- yfinance - Yahoo Finance API integration

### Frontend
- React 19 - UI framework
- Vite - Build tool and dev server

## Features

### RAG Workflow
1. User submits natural language query
2. Vector search finds relevant database tables/columns
3. GPT-4 generates SQL query with context
4. Query executes against PostgreSQL
5. Results analyzed and summarized by AI
6. External APIs enriched data when relevant

### Query Explainability
- Generated SQL displayed
- Execution time tracked
- Relevant tables shown
- Agent reasoning logged
- All queries logged to database

### Data Sources
- **Excel Import**: Portfolio company data
- **Yahoo Finance**: Real-time stock data, financials
- **SEC EDGAR**: Company filings
- **Synthetic Data**: 5000+ performance metrics

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

After database changes:
```bash
curl -X POST http://localhost:8000/api/index-schema
```

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
├── src/
│   ├── App.jsx              # React UI
│   └── App.css
└── README.md
```

## Future Improvements

- Add more sophisticated query planning
- Implement query result caching
- Add support for complex joins across 3+ tables
- Implement policy agent for query validation
- Add real-time data streaming
- Support for multi-turn conversations
- Add authentication and user management
- Deploy to cloud platform

## License

MIT
