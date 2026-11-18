# API reference

[← Back to the README](../README.md)

The HTTP endpoints, with an example request and the response format.

Interactive docs are served at `/docs`. All endpoints except health require
`X-API-Key` when auth is enabled.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/query` | Answer a natural-language question |
| `GET`  | `/api/history?limit=&offset=` | Recent queries, newest first |
| `GET`  | `/api/stats` | Row counts, query success rate, index size |
| `POST` | `/api/index-schema` | Rebuild the schema vector index (run after migrations) |
| `GET`  | `/api/health` | Readiness: `200` when the database is reachable, else `503`; reports local/remote LLM |
| `GET`  | `/api/health/llm` | Probe the LLM endpoint: reachable, model served, latency, cache stats |
| `GET`  | `/api/metrics/summary?window=` | Tokens, cost, latency percentiles, error rate, model usage, worst queries |
| `GET`  | `/api/metrics/timeseries?window=` | Usage, cost, failures and latency per time bucket |
| `GET`  | `/api/metrics/recent?limit=` | Latest requests with per-stage latency |

```bash
curl -s localhost:8000/api/query \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"query": "What were Berkshire Hathaway'"'"'s 5 largest holdings in its latest 13F filing?"}'
```

The response includes `answer`, `summary`, `insights`, `sql`, `data`,
`relevant_tables`, `enriched_data`, `agent_flow` (status per stage), `trace`,
`citations` (tables, scores, column lineage, row keys), `verification`
(per-claim verdicts with evidence) and `usage` (tokens, cost, cache hits,
latency per stage).
A question the pipeline cannot answer safely returns `200` with
`"success": false` and a user-facing `error`. HTTP errors (`401`, `422`, `429`,
`500`) are reserved for problems with the request itself or the server.
