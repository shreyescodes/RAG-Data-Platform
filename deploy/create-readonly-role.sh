#!/usr/bin/env bash
# Create (or update) the SELECT-only role that runs LLM-generated SQL.
# Run once after the first seed; safe to run again.
#   ./deploy/create-readonly-role.sh '<password>'
# Then add to .env and restart the backend:
#   QUERY_DATABASE_URL=postgresql://rag_readonly:<password>@db:5432/<POSTGRES_DB>
#   ./deploy/compose.sh up -d backend
# Background: docs/security.md ("Recommended: a SELECT-only role").
set -euo pipefail
cd "$(dirname "$0")/.."

password=${1:?usage: create-readonly-role.sh <password>}

./deploy/compose.sh exec -T -e RO_PASSWORD="$password" db sh -c \
    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v pw="$RO_PASSWORD" -v db="$POSTGRES_DB"' <<'SQL'
SELECT NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rag_readonly') AS create_role \gset
\if :create_role
    CREATE ROLE rag_readonly LOGIN;
\endif
ALTER ROLE rag_readonly PASSWORD :'pw';
GRANT CONNECT ON DATABASE :"db" TO rag_readonly;
GRANT USAGE ON SCHEMA public TO rag_readonly;
GRANT SELECT ON companies, financial_statements, portfolio_companies,
                performance_metrics, market_data TO rag_readonly;
ALTER ROLE rag_readonly SET statement_timeout = '15s';
SQL

echo "rag_readonly is ready. Set QUERY_DATABASE_URL in .env and run: ./deploy/compose.sh up -d backend"
