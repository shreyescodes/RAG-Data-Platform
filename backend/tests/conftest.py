"""Shared fixtures.

Tests run with a deterministic fake embedder and a scripted fake LLM, so they
need no network, model weights or API keys. The database is a throwaway SQLite
file unless TEST_DATABASE_URL points at a disposable PostgreSQL database (CI
does this); its tables are dropped and recreated.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Configure the environment before any `app` module reads settings.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="rag-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.environ.get(
            "TEST_DATABASE_URL", f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
        ),
        "API_KEY": "test-api-key",
        "LLM_API_KEY": "",
        "ENRICHMENT_ENABLED": "false",
        "FAISS_INDEX_PATH": str(_TMP_DIR / "faiss" / "index"),
        "RATE_LIMIT_QUERY": "1000/minute",
        "RATE_LIMIT_ADMIN": "1000/minute",
        "LOG_LEVEL": "WARNING",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Engine, delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.container import ServiceContainer  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.db.models import Base, QueryLog  # noqa: E402
from app.db.session import get_engine, get_session_factory  # noqa: E402
from app.main import create_app  # noqa: E402
from app.rag.schema_indexer import SchemaIndexer  # noqa: E402
from app.rag.vector_store import FAISSVectorStore  # noqa: E402
from tests.factories import seed_reference_data  # noqa: E402
from tests.fakes import FakeChatModel, HashingEmbedder  # noqa: E402

API_KEY = os.environ["API_KEY"]


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    get_engine().dispose()
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def engine() -> Engine:
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with get_session_factory()() as session:
        seed_reference_data(session)
    return engine


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session
        session.execute(delete(QueryLog))
        session.commit()


@pytest.fixture
def embedder() -> HashingEmbedder:
    return HashingEmbedder()


@pytest.fixture
def vector_store(tmp_path: Path, embedder: HashingEmbedder) -> FAISSVectorStore:
    return FAISSVectorStore(embedder, tmp_path / "index")


@pytest.fixture
def indexer(vector_store: FAISSVectorStore) -> SchemaIndexer:
    indexer = SchemaIndexer(vector_store)
    indexer.index()
    return indexer


@pytest.fixture
def fake_llm() -> FakeChatModel:
    return FakeChatModel()


@pytest.fixture
def services(
    indexer: SchemaIndexer, vector_store: FAISSVectorStore, fake_llm: FakeChatModel
) -> ServiceContainer:
    # The app lifespan closes the HTTP client on shutdown.
    return ServiceContainer(
        vector_store=vector_store,
        schema_indexer=indexer,
        chat_model=fake_llm,
        http_client=httpx.AsyncClient(),
        market_data=None,
        sec_edgar=None,
    )


@pytest.fixture
def app(services: ServiceContainer, engine: Engine) -> FastAPI:
    application = create_app()
    application.state.services = services
    return application


@pytest.fixture
def client(app: FastAPI, db: Session) -> Iterator[TestClient]:
    limiter.reset()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}
