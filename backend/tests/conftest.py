import os

# Must be set BEFORE any app module is imported.
# DATABASE_URL is now required (no default) — set a SQLite in-memory URL for tests.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("OPENAI_API_KEY", "dummy_key")
os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:5173")

import pytest  # noqa: E402
from backend.api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

TEST_API_KEY = os.environ["API_KEY"]


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Return headers with a valid API key for authenticated endpoints."""
    return {"X-API-Key": TEST_API_KEY}
