from unittest.mock import patch

from app.main import app
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

client = TestClient(app)

DB_TOUCHED = AssertionError("/metrics must not touch the database")


def _requests_total(handler: str, status: str) -> float:
    labels = {"handler": handler, "method": "GET", "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def test_metrics_exposes_request_metrics():
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_metrics_does_not_touch_the_database():
    with (
        patch("app.main.is_db_alive", side_effect=DB_TOUCHED),
        patch("app.main._is_permanently_broken", side_effect=DB_TOUCHED),
    ):
        response = client.get("/metrics")

    assert response.status_code == 200


def test_metrics_answers_while_transient_chaos_flag_is_set():
    with patch.dict("app.main.CHAOS_STATE", {"broken": True}):
        response = client.get("/metrics")

    assert response.status_code == 200


def test_chaos_503_is_counted():
    before = _requests_total("/orders", "5xx")
    with patch.dict("app.main.CHAOS_STATE", {"broken": True}):
        response = client.get("/orders")

    assert response.status_code == 503
    assert _requests_total("/orders", "5xx") == before + 1


def test_probe_and_scrape_traffic_is_not_counted():
    with (
        patch("app.main.is_db_alive", return_value=True),
        patch("app.main._is_permanently_broken", return_value=False),
    ):
        client.get("/health")
    client.get("/livez")
    client.get("/metrics")

    for handler in ("/health", "/livez", "/metrics"):
        assert _requests_total(handler, "2xx") == 0.0
