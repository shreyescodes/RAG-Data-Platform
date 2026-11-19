# Testing and quality

[← Back to the README](../README.md)

How the code is tested and what CI enforces.

```bash
make check          # ruff lint + format check, mypy --strict, backend and frontend tests
make eval-offline   # retrieval and hallucination evaluations (no database or LLM)
make test-e2e       # Playwright browser tests against a production build
```

- **Backend:** 442 pytest tests, including attack cases for the SQL validator
  and PII redactor, retry and repair paths, planted hallucinations, cache
  poisoning, private history, saved chats, streaming progress, daily limits and
  metrics aggregation. They run with a fake embedder, reranker
  and LLM, so they need no network or API keys, and pass on SQLite and
  PostgreSQL. Coverage is 97%, enforced at 85%.
- **Frontend:** 91 Vitest and Testing Library tests for the API client, chart
  inference and layout, formatting, citations, the fact check, the
  observability dashboard and the main user flows.
- **Browser:** 10 Playwright tests drive a production build in desktop and
  mobile Chromium: asking, follow-ups, new chats, reopening a saved chat,
  refusals, the collapsible sidebar, the mobile drawer and the dashboard. The
  API is mocked in the browser, so they need no backend or LLM.
- **Load:** `python -m eval.load` measures the backend under concurrent users
  with a stand-in LLM ([results](load-test.md)).
- **End to end:** `make eval` scores the live pipeline against ground-truth
  SQL (see [Measured accuracy](results.md)) and reports citations,
  fact-check flags and usage per case. It needs a seeded database and an LLM
  (hosted or local), so it runs on demand rather than in CI.
- **Offline evaluations:** `make eval-offline` measures retrieval quality
  (dense vs hybrid vs reranked, real local models) and the hallucination
  detector (labelled claims). Both run in CI as regression gates.
- **CI** (GitHub Actions) runs:
  1. Lint and strict type checks.
  2. Migrations on PostgreSQL 16, including a model/migration drift check
     (`alembic check`) and a downgrade round trip.
  3. The test suite against PostgreSQL.
  4. The offline retrieval and hallucination evaluations.
  5. Frontend lint, tests and build on Node 22.22 and 26, the oldest and
     newest supported.
  6. Playwright browser tests.
  7. Security scans: gitleaks over the whole git history, pip-audit and
     npm audit for known vulnerabilities in dependencies.
  8. Docker image builds, then a Grype scan that fails on critical
     vulnerabilities with a fix available.
