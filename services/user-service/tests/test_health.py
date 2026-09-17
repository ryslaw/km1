from fastapi.testclient import TestClient
from app.main import app
from unittest.mock import patch

client = TestClient(app)


def test_health_returns_200_when_db_is_alive():
    with patch("app.main.is_db_alive", return_value=True):
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "user-service"}
