# Demo Video Script (5 Minutes)

## Segment 1: Problem Summary & Approach (0:30)

**Script:**
"Hello! I've built a full-stack RAG platform that enables natural language querying of financial data using a multi-agent architecture.

The challenge was to create a system that can:
1. Store and manage complex financial data across multiple tables
2. Understand natural language questions
3. Generate and execute SQL queries intelligently
4. Provide explainable, insightful answers

My approach uses OpenAI embeddings for semantic search, GPT-4 for SQL generation, and a coordinated multi-agent system to deliver comprehensive answers."

---

## Segment 2: Dataset Design & ERD (0:45)

**Show:** ARCHITECTURE.md database schema section or draw ERD

**Script:**
"The database consists of 6 tables:

1. **Companies** - Master data with ticker, sector, industry
2. **Financial Statements** - Income statements, balance sheets, cash flow - over 120 records with 18+ columns
3. **Portfolio Companies** - PE fund investment tracking
4. **Performance Metrics** - ARR, MRR, churn, CAC, LTV - 5000+ synthetic records
5. **Market Data** - Historical stock prices from Yahoo Finance - 7000+ data points
6. **Query Logs** - Query history for debugging

Tables have proper foreign key relationships. Two tables exceed 5000 rows as required. Data synthesized from Yahoo Finance for 10 public companies plus generated metrics."

**Show:** Database stats from `/api/stats` endpoint

---

## Segment 3: RAG Workflow Demo (1:30)

**Show:** Live demo of frontend

**Script:**
"Let me demonstrate the RAG workflow. I'll open the web interface.

**Query 1:** 'List all companies in the technology sector'

Watch the workflow:
1. Query is embedded using OpenAI
2. Vector search finds relevant tables (companies table)
3. GPT-4 generates this SQL query: `SELECT * FROM companies WHERE sector = 'Technology'`
4. Query executes and returns results
5. Analysis agent summarizes: '5 technology companies found'
6. Full results displayed with execution time

**Query 2:** 'What is the average revenue across all financial statements?'

Notice:
- More complex SQL with aggregation
- Natural language answer: 'The average revenue is $125.3M'
- Insights provided
- Execution time: ~300ms

**Query 3:** 'Show portfolio companies with over 1 million ARR'

This requires:
- JOIN between portfolio_companies and performance_metrics
- Filtering condition
- Generated SQL handles the complexity
- Results show company details with metrics"

---

## Segment 4: Agent Architecture Explanation (1:00)

**Show:** ARCHITECTURE.md diagram or code

**Script:**
"The multi-agent system has three specialized agents coordinated by an orchestrator:

**1. Retrieval Agent:**
- Performs semantic search in FAISS vector store
- Finds relevant tables and columns
- Generates SQL using GPT-4 with schema context
- Executes query safely with parameterized statements
- Returns structured results

**2. Analysis Agent:**
- Takes query results
- Generates human-readable summary
- Extracts 2-3 key insights
- Provides natural language answer

**3. Enrichment Agent:**
- Detects if external data is needed (keywords like 'stock', 'price', 'SEC')
- Fetches from Yahoo Finance API
- Fetches from SEC EDGAR
- Merges external context with query results

All agents log their reasoning steps for complete explainability. The orchestrator manages the flow and handles errors gracefully."

**Show:** Example of agent reasoning in API response

---

## Segment 5: Scalability Plan & Future Improvements (1:00)

**Show:** ARCHITECTURE.md scalability section

**Script:**
"Current implementation handles 10-50 concurrent queries with sub-second response times.

**Scalability Plan:**

**Horizontal Scaling:**
- Deploy multiple API servers behind load balancer
- Use Redis for session management and caching
- Implement Celery for background tasks

**Data Layer:**
- Migrate FAISS to Pinecone or Weaviate for distributed vector search
- Add PostgreSQL read replicas
- Implement query result caching

**Performance:**
- Pre-compute common aggregations
- Add embedding cache
- Implement SQL query plan optimization

**Features:**
- Add Policy Agent for query validation and safety
- Support multi-turn conversations with context
- Real-time data streaming
- Advanced visualization with charts
- User authentication and role-based access

**Monitoring:**
- Prometheus for metrics
- Grafana dashboards
- Alert system for failures
- Query performance tracking"

---

## Segment 6: Code/API Walkthrough (0:15)

**Show:** Quick tour of codebase

**Script:**
"Quick code overview:

**Backend structure:**
- `api/main.py` - FastAPI endpoints
- `agents/` - Multi-agent implementation
- `rag/` - Vector store and SQL generation
- `db/models.py` - Database schema
- Clean, modular, production-ready

**API endpoints:**
- POST /api/query - Main query endpoint
- GET /api/stats - Platform statistics
- GET /api/history - Query logs

**Frontend:**
- React 19 with modern UI
- Real-time query results
- Execution metrics display
- Mobile responsive

Total codebase: ~2,000+ lines
All documented with README, QUICKSTART, and ARCHITECTURE guides."

---

## Closing (0:00)

**Script:**
"Thank you! The platform is fully functional with comprehensive documentation. All code is on GitHub. Questions welcome!"

---

## Demo Checklist

Before recording:

- [ ] PostgreSQL running
- [ ] Backend server started
- [ ] Frontend running
- [ ] Database has data (run setup_data.py)
- [ ] Test all example queries
- [ ] Open relevant documentation files
- [ ] Browser console clear
- [ ] Screen recording software ready

## Example Queries to Show

1. Simple: "How many companies are in the database?"
2. Aggregation: "What is the total market cap across all companies?"
3. Join: "Show portfolio companies with their latest ARR"
4. Filter: "List companies with revenue over 10 million"
5. Complex: "What is the average churn rate for SaaS companies?"

## URLs to Have Ready

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000/docs
- Stats endpoint: http://localhost:8000/api/stats
- GitHub repo (if pushed)

## Tips for Recording

1. Use Loom for screen recording
2. Speak clearly and at moderate pace
3. Show live interactions, not just slides
4. Highlight key features as you demo
5. Keep within 5-minute time limit
6. Test recording setup first
7. Have water nearby
8. Minimize distractions

Good luck with your demo! 🚀
