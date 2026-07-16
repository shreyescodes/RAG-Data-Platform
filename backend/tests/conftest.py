import os
os.environ["OPENAI_API_KEY"] = "dummy_key"

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI application."""
    return TestClient(app)
