from unittest.mock import patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_returns_200_when_db_is_alive():
    with patch("app.main.is_db_alive", return_value=True), patch("app.main._is_permanently_broken", return_value=False):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "order-service"}
