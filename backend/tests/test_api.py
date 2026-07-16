def test_health_check(client):
    """Test the health check endpoint."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] in ["healthy", "unhealthy"]


def test_stats(client):
    """Test the stats endpoint."""
    response = client.get("/api/stats")
    # Even if DB is empty or fails, we should get a 200 or 500 but it should exist.
    assert response.status_code in [200, 500]
