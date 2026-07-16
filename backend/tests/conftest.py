import os

os.environ["OPENAI_API_KEY"] = "dummy_key"

import pytest  # noqa: E402
from backend.api.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    return TestClient(app)
