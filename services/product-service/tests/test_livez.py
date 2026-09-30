from unittest.mock import patch

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

DB_TOUCHED = AssertionError("/livez must not touch the database")


def test_livez_returns_200_without_touching_db():
    with (
        patch("app.main.is_db_alive", side_effect=DB_TOUCHED),
        patch("app.main._is_permanently_broken", side_effect=DB_TOUCHED),
    ):
        response = client.get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "product-service"}


def test_livez_returns_503_when_transient_chaos_flag_is_set():
    with (
        patch("app.main.is_db_alive", side_effect=DB_TOUCHED),
        patch("app.main._is_permanently_broken", side_effect=DB_TOUCHED),
        patch.dict("app.main.CHAOS_STATE", {"broken": True}),
    ):
        response = client.get("/livez")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "service": "product-service"}
