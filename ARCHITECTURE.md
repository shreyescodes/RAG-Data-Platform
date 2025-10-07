# RAG Platform Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER INTERFACE                           │
│                    (React Frontend - Port 5173)                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP/REST
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API LAYER                                │
│                    (FastAPI - Port 8000)                         │
│  Endpoints: /api/query, /api/history, /api/stats, /api/health   │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AGENT ORCHESTRATOR                            │
│              Coordinates Multi-Agent Workflow                    │
└───┬──────────────────┬──────────────────┬──────────────────────┘
    │                  │                  │
    ▼                  ▼                  ▼
┌──────────┐    ┌──────────┐    ┌─────────────┐
│ RETRIEVAL│    │ ANALYSIS │    │ ENRICHMENT  │
│  AGENT   │    │  AGENT   │    │   AGENT     │
└────┬─────┘    └────┬─────┘    └──────┬──────┘
     │               │                  │
     ▼               ▼                  ▼
┌──────────┐    ┌──────────┐    ┌─────────────┐
│  Vector  │    │   GPT-4  │    │   External  │
│  Store   │    │ OpenAI   │    │    APIs     │
│ (FAISS)  │    │          │    │ (Yahoo/SEC) │
└────┬─────┘    └──────────┘    └─────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER                              │
│                   (PostgreSQL - Port 5432)                       │
│  Tables: companies, financial_statements, portfolio_companies,   │
│          performance_metrics, market_data, query_logs            │
└─────────────────────────────────────────────────────────────────┘
```

## Multi-Agent Workflow

### Phase 1: Query Reception
```
User Query → API Endpoint → Orchestrator
```

### Phase 2: Retrieval Agent
```
1. Receive natural language query
2. Semantic search in vector store
3. Find relevant tables and columns
4. Generate SQL using GPT-4 with schema context
5. Execute SQL against PostgreSQL
6. Return results with metadata
```

**Key Components:**
- `schema_indexer.py` - Indexes database schema into vectors
- `vector_store.py` - FAISS-based semantic search
- `sql_generator.py` - GPT-4 powered SQL generation
- `retrieval_agent.py` - Orchestrates retrieval flow

### Phase 3: Analysis Agent
```
1. Receive query results from Retrieval Agent
2. Analyze data patterns and trends
3. Generate human-readable summary
4. Extract key insights (2-3 points)
5. Create natural language answer
```

**Key Components:**
- `analysis_agent.py` - GPT-4 powered analysis and summarization

### Phase 4: Enrichment Agent
```
1. Detect if external data is needed
2. Fetch from Yahoo Finance (stock prices, financials)
3. Fetch from SEC EDGAR (company filings)
4. Merge with query results
5. Return enriched context
```

**Key Components:**
- `enrichment_agent.py` - External API integration

### Phase 5: Response Assembly
```
1. Combine all agent outputs
2. Log query to database
3. Track execution time
4. Return comprehensive response
```

## Data Flow

### Semantic Retrieval Flow
```
Natural Language Query
    ↓
Embedding Generation (OpenAI)
    ↓
Vector Similarity Search (FAISS)
    ↓
Relevant Schema Elements
    ↓
SQL Generation (GPT-4)
    ↓
Query Execution (PostgreSQL)
    ↓
Results
```

### Response Format
```json
{
  "success": true,
  "query": "user's natural language query",
  "sql": "generated SQL query",
  "answer": "natural language answer",
  "summary": "brief summary of findings",
  "insights": ["insight 1", "insight 2"],
  "data": [...],
  "row_count": 42,
  "relevant_tables": ["table1", "table2"],
  "enriched_data": {},
  "execution_time_ms": 234.5,
  "agent_flow": {
    "retrieval": "completed",
    "analysis": "completed",
    "enrichment": "skipped"
  }
}
```

## Database Schema

### Core Tables

**companies**
- Company master data
- Ticker symbols
- Sector and industry classification

**financial_statements** (5000+ rows)
- Income statements
- Balance sheets
- Cash flow statements
- Quarterly and annual data

**portfolio_companies**
- PE fund investment tracking
- Investment amounts and valuations
- Ownership percentages

**performance_metrics** (5000+ rows)
- ARR, MRR, customer counts
- Churn rates, CAC, LTV
- Revenue and EBITDA multiples

**market_data**
- Historical stock prices
- Daily OHLCV data
- Volume and adjusted close

**query_logs**
- Query history
- SQL generated
- Agent reasoning
- Performance metrics

## Vector Store Design

### Schema Indexing
```
For each table:
  - Index table name and description
  - Index each column with type information
  - Index foreign key relationships

Vector Embeddings:
  - Model: text-embedding-3-small (OpenAI)
  - Dimension: 1536
  - Storage: FAISS (local file system)

Search Strategy:
  - Top-k similarity search (k=5 for tables, k=10 for columns)
  - Distance metric: L2 (Euclidean)
```

## Technology Stack

### Backend
- **FastAPI**: Modern async web framework
- **SQLAlchemy**: ORM for database operations
- **Pydantic**: Data validation and serialization
- **OpenAI**: GPT-4 for SQL generation and analysis
- **FAISS**: Vector similarity search
- **Pandas**: Data manipulation
- **yfinance**: Yahoo Finance API client

### Frontend
- **React 19**: UI framework
- **Vite**: Build tool and dev server
- **CSS3**: Modern styling with gradients and animations

### Data
- **PostgreSQL 12+**: Relational database
- **Yahoo Finance**: Real-time financial data
- **SEC EDGAR**: Company filings (optional)

## Scalability Considerations

### Current Implementation
- Single-server deployment
- In-memory vector store (FAISS)
- Synchronous processing
- No caching layer

### Future Improvements
1. **Horizontal Scaling**
   - Deploy API servers behind load balancer
   - Use Redis for session management
   - Implement distributed task queue (Celery)

2. **Vector Store Optimization**
   - Migrate to Pinecone or Weaviate for distributed search
   - Implement incremental indexing
   - Add embedding cache

3. **Query Optimization**
   - Add query result caching (Redis)
   - Implement SQL query plan analysis
   - Pre-compute common aggregations

4. **Agent Improvements**
   - Add Policy Agent for query validation
   - Implement parallel agent execution
   - Add reasoning chain visualization

5. **Data Pipeline**
   - Real-time data ingestion
   - Scheduled batch updates
   - Change data capture (CDC)

## Security Considerations

### Current Implementation
- API key authentication for OpenAI
- Database credentials in environment variables
- No user authentication

### Production Requirements
- User authentication (JWT tokens)
- Role-based access control (RBAC)
- SQL injection prevention (parameterized queries)
- Rate limiting on API endpoints
- Input validation and sanitization
- Audit logging for sensitive queries

## Performance Metrics

### Expected Performance
- Query latency: 200-500ms (simple queries)
- Query latency: 500-2000ms (complex joins)
- Vector search: <50ms
- SQL generation: 200-400ms
- Analysis: 300-600ms

### Monitoring
- Query logs stored in database
- Execution time tracked per query
- Agent reasoning logged for debugging
- Success/failure rates in `/api/stats`

## Error Handling

### Retry Logic
- Vector search: 3 retries with exponential backoff
- SQL generation: 2 retries if malformed
- External APIs: 2 retries with 1s delay

### Fallback Strategies
- If SQL generation fails: Return error with context
- If analysis fails: Return raw query results
- If enrichment fails: Continue without external data

## Development Workflow

1. **Database Changes**
   - Update models in `db/models.py`
   - Run migrations
   - Re-index schema: `POST /api/index-schema`

2. **Agent Updates**
   - Modify agent logic in `agents/`
   - Test with example queries
   - Update reasoning logs

3. **Frontend Changes**
   - Update React components
   - Run `npm run build`
   - Test UI with backend

## Testing Strategy

### Unit Tests
- Test individual agents
- Test SQL generation
- Test vector search

### Integration Tests
- Test full query workflow
- Test API endpoints
- Test database operations

### End-to-End Tests
- Test complete user journey
- Test error scenarios
- Test performance under load
