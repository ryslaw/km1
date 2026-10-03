from unittest.mock import MagicMock, patch

from app.database import get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

client = TestClient(app)

DB_DOWN = OperationalError("SELECT 1", {}, Exception("db down"))


def _unreachable_db():
    session = MagicMock()
    session.query.side_effect = DB_DOWN
    yield session


def test_regular_endpoint_returns_503_json_when_db_is_down():
    app.dependency_overrides[get_db] = _unreachable_db
    try:
        with patch("app.main._is_permanently_broken", side_effect=DB_DOWN):
            response = client.get("/products")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_health_returns_its_own_503_body_when_db_is_down():
    with (
        patch("app.main._is_permanently_broken", side_effect=DB_DOWN),
        patch("app.main.is_db_alive", return_value=False),
    ):
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "service": "product-service"}


def test_docs_are_served_when_db_is_down():
    with patch("app.main._is_permanently_broken", side_effect=DB_DOWN):
        response = client.get("/docs")

    assert response.status_code == 200
