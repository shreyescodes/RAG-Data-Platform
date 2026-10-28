# syntax=docker/dockerfile:1

# ---- Build: resolve dependencies into an isolated virtualenv -----------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# CPU-only PyTorch is several GB smaller than the default CUDA build and is all
# the embedding model needs.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- Runtime ------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HF_HOME=/opt/hf-cache \
    HF_HUB_DISABLE_TELEMETRY=1

RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=builder /opt/venv /opt/venv

# Bake the embedding model into the image so containers start offline.
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
RUN python -c "from sentence_transformers import SentenceTransformer as M; M('${EMBEDDING_MODEL}')" \
    && chmod -R a+rX "$HF_HOME"
ENV HF_HUB_OFFLINE=1

WORKDIR /app
COPY --chown=app:app alembic.ini docker-entrypoint.sh ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app app ./app
RUN chmod +x docker-entrypoint.sh && mkdir -p /app/data && chown app:app /app/data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import sys, urllib.request as u; sys.exit(u.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status != 200)"

ENTRYPOINT ["./docker-entrypoint.sh"]
# Trust X-Forwarded-For only from FORWARDED_ALLOW_IPS (default 127.0.0.1).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
