#!/bin/sh
# Container entrypoint: apply migrations and ensure a schema index exists,
# then exec the given command (uvicorn by default).
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Applying database migrations..."
    alembic upgrade head
fi

index_file="${FAISS_INDEX_PATH:-data/faiss_index}.index"
if [ ! -f "$index_file" ]; then
    echo "No schema index found; building one..."
    python -m app.cli index-schema
fi

exec "$@"
