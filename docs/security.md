# Security

## Threat model

The platform turns untrusted natural language into SQL that runs against a
database. The main risks, and the controls for each:

| Risk | Controls |
|------|----------|
| Prompt injection leading to destructive or exfiltrating SQL | Static validation, a read-only transaction, statement timeout, row cap, table allow-list, optional least-privilege role |
| Reading other users' data (query history) | `query_logs` is excluded from the schema index and rejected by the validator |
| Sensitive data sent to third-party LLMs | PII redaction before any processing; schema embeddings computed locally |
| Unauthorised or abusive API use | API-key auth, per-IP rate limits, input length limits |
| Secret leakage | Secrets held as `SecretStr` (masked in logs and reprs); the API key is added by the proxy and never shipped to the browser |
| Internal detail leaking in errors | Clients only see curated `user_message` strings; stack traces go to logs with a request ID |

## Generated SQL

Every statement passes through [`sql_validator.py`](../backend/app/rag/sql_validator.py),
which rejects:

- anything other than exactly one query (`SELECT`, set operations, CTEs)
- write or DDL nodes anywhere in the tree, including data-modifying CTEs,
  `SELECT ... INTO` and `FOR UPDATE`
- functions starting with `pg_` or `lo_`, `dblink`, `current_setting` and
  `set_config`
- tables outside the allow-list, and any schema-qualified table other than
  `public` (which blocks `pg_catalog` and `information_schema`)

The validator then enforces `LIMIT <= MAX_RESULT_ROWS`.

Execution ([`readonly.py`](../backend/app/db/readonly.py)) on PostgreSQL then
runs `SET TRANSACTION READ ONLY` and `SET LOCAL statement_timeout`, and always
rolls back. Writes are therefore refused by the database itself even if the
validator were bypassed.

### Recommended: a SELECT-only role

Set `QUERY_DATABASE_URL` to a role that can only read the domain tables:

```sql
CREATE ROLE rag_readonly LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE rag_data TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;
GRANT SELECT ON companies, financial_statements, portfolio_companies,
                performance_metrics, market_data TO rag_readonly;
ALTER ROLE rag_readonly SET statement_timeout = '15s';
```

## PII redaction

[`pii_redactor.py`](../backend/app/utils/pii_redactor.py) masks the following
in the incoming question:

- email addresses
- IPv4 addresses
- US SSNs
- payment card numbers (13–19 digits that pass the Luhn check)
- phone numbers (separators or a `+` country code are required)

The redacted text is what reaches the LLM, the logs, the audit table and the
response. Bare digit runs are deliberately left alone, so financial values
such as `1000000` survive. Redaction is pattern-based. It reduces exposure
but is not a guarantee, and it does not detect names or addresses.

## Deployment checklist

- `ENVIRONMENT=production`. Startup then fails without `API_KEY` or with
  wildcard CORS.
- A long random `API_KEY`, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- `QUERY_DATABASE_URL` pointing at a SELECT-only role.
- TLS terminated in front of nginx.
- `EXPOSE_DOCS=false` if the OpenAPI schema should not be public.
- `FORWARDED_ALLOW_IPS` restricted to your proxy so clients cannot spoof
  `X-Forwarded-For` to evade rate limits.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's
[private vulnerability reporting](https://github.com/shreyescodes/RAG-Data-Platform/security/advisories/new)
instead.
