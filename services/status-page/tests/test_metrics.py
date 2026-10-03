from app.main import app
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

client = TestClient(app)


def _requests_total(handler: str, status: str) -> float:
    labels = {"handler": handler, "method": "GET", "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def test_metrics_exposes_request_metrics():
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_probe_and_scrape_traffic_is_not_counted():
    client.get("/health")
    client.get("/metrics")

    for handler in ("/health", "/metrics"):
        assert _requests_total(handler, "2xx") == 0.0
