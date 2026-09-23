import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client


def test_home(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {
        "service": "observability-lab",
        "status": "ok",
    }


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
    }


def test_error_endpoint(client):
    response = client.get("/error")

    assert response.status_code == 500
    assert response.get_json() == {
        "error": "intentional application error",
    }


def test_work(client):
    response = client.get("/work?delay=0")

    assert response.status_code == 200
    assert response.get_json() == {
        "worked": True,
        "delay": 0.0,
    }


def test_metrics(client):
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "app_http_requests_total" in response.get_data(as_text=True)


def test_ready_when_dependencies_are_unavailable(client):
    with patch("app.db_conn", side_effect=Exception("database unavailable")):
        with patch(
            "app.get_redis",
            return_value=MagicMock(
                ping=MagicMock(
                    side_effect=Exception("redis unavailable")
                )
            ),
        ):
            response = client.get("/ready")

    assert response.status_code == 503

    data = response.get_json()

    assert data["status"] == "not_ready"
    assert data["checks"]["database"].startswith("error:")
    assert data["checks"]["redis"].startswith("error:")
