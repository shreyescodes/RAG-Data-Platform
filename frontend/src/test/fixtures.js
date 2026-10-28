export const successResult = {
  success: true,
  query: 'Top companies by ARR',
  sql: 'SELECT name, arr FROM performance_metrics LIMIT 500',
  answer: 'Atlas Analytics has the highest ARR.',
  summary: 'ARR ranges from $1M to $12M.',
  insights: ['Atlas leads by a wide margin.', 'Most companies are Series A.'],
  data: [
    { name: 'Atlas Analytics', arr: 12000000 },
    { name: 'Beacon Cloud', arr: 1500000.5 },
  ],
  row_count: 2,
  relevant_tables: ['performance_metrics', 'companies'],
  enriched_data: {},
  execution_time_ms: 1834.2,
  agent_flow: { retrieval: 'completed', enrichment: 'skipped', analysis: 'completed' },
  trace: [
    { agent: 'retrieval', step: 'sql_executed', detail: { rows: 2 }, timestamp: '2026-10-28T10:00:00Z' },
  ],
  error: null,
}

export const failedResult = {
  ...successResult,
  success: false,
  answer: null,
  data: [],
  row_count: 0,
  error: 'The generated query was rejected by the SQL safety checks.',
  agent_flow: { retrieval: 'failed', enrichment: 'skipped', analysis: 'skipped' },
}

export const stats = {
  queries: { total: 3, successful: 2, success_rate: 66.67 },
  database: {
    companies: 90,
    financial_statements: 120,
    portfolio_companies: 80,
    performance_metrics: 5398,
    market_data: 5020,
  },
  vector_store: { total_documents: 74 },
}

export const history = {
  total: 1,
  limit: 8,
  offset: 0,
  history: [
    {
      id: 1,
      query: 'Average churn by stage',
      sql: 'SELECT 1',
      answer: 'About 1.5%.',
      success: true,
      error: null,
      execution_time_ms: 900,
      created_at: '2026-10-28T09:00:00',
    },
  ],
}
