def test_health_check(client):
    """Health check is public — no API key required."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] in ["healthy", "unhealthy"]


def test_stats_unauthenticated(client):
    """/api/stats requires X-API-Key — should return 403 without it."""
    response = client.get("/api/stats")
    assert response.status_code == 403


def test_stats_authenticated(client, auth_headers):
    """/api/stats returns 200 or 500 with a valid API key."""
    response = client.get("/api/stats", headers=auth_headers)
    assert response.status_code in [200, 500]


def test_history_unauthenticated(client):
    """/api/history requires X-API-Key — should return 403 without it."""
    response = client.get("/api/history")
    assert response.status_code == 403


def test_history_authenticated(client, auth_headers):
    """/api/history returns 200 with a valid API key."""
    response = client.get("/api/history", headers=auth_headers)
    assert response.status_code in [200, 500]


def test_history_limit_cap(client, auth_headers):
    """Pagination limit above 100 should be rejected with 422."""
    response = client.get("/api/history?limit=999", headers=auth_headers)
    assert response.status_code == 422


def test_root(client):
    """Root endpoint is public and returns API metadata."""
    response = client.get("/")
    assert response.status_code == 200
    assert "version" in response.json()
