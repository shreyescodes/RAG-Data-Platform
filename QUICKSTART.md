# Quick Start Guide

## Prerequisites

Make sure you have:
- Python 3.8+ installed
- PostgreSQL running on `localhost:5432` with database `RAG`
- OpenAI API key (in `.env` file)

## Installation & Setup

### 1. Install Backend Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Initialize Database

```bash
python setup_data.py
```

This creates tables, loads data, and indexes the schema. Takes ~5-10 minutes.

### 3. Start Backend Server

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Backend runs on `http://localhost:8000`

### 4. Start Frontend (New Terminal)

```bash
cd ..
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`

## Testing the Platform

Open `http://localhost:5173` and try these queries:

1. "List all companies in the technology sector"
2. "What is the average revenue across all companies?"
3. "Show me portfolio companies with over 1 million ARR"
4. "What's the total market data points for AAPL?"

## API Testing

Test the API directly:

```bash
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How many companies are in the database?"}'
```

Check platform stats:

```bash
curl http://localhost:8000/api/stats
```

## Troubleshooting

### Database Connection Error
- Ensure PostgreSQL is running
- Check credentials in `.env` file
- Create database: `createdb RAG`

### Import Errors
- Install dependencies: `pip install -r backend/requirements.txt`

### API Not Responding
- Check if port 8000 is available
- Verify backend server is running

## Architecture Flow

```
User Query
  → Frontend (React)
  → API (FastAPI)
  → Retrieval Agent (Vector Search + SQL Generation)
  → Analysis Agent (Summarization + Insights)
  → Enrichment Agent (External APIs)
  → Response to User
```

## Data Summary

After setup, you'll have:
- 10+ companies (from Yahoo Finance)
- 5000+ performance metrics
- 100+ financial statements
- Market data for multiple stocks
- Full vector search index

Enjoy exploring the platform!
