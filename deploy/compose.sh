#!/usr/bin/env bash
# docker compose with the production files and env files, from anywhere:
#   ./deploy/compose.sh ps
#   ./deploy/compose.sh logs -f backend
#   ./deploy/compose.sh exec backend python -m app.cli seed
#
# .env holds secrets and settings; .deploy.env holds only IMAGE_TAG, the
# image version currently deployed (written by deploy.sh).
set -euo pipefail
cd "$(dirname "$0")/.."

env_files=(--env-file .env)
[ -f .deploy.env ] && env_files+=(--env-file .deploy.env)

exec docker compose "${env_files[@]}" -f docker-compose.yml -f docker-compose.prod.yml "$@"
