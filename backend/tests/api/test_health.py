import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness():
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_when_ready(monkeypatch):
    from app.core.database import engine
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a, **k): pass

    monkeypatch.setattr(engine, "connect", lambda *a, **k: FakeConn())

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["db"] == "connected"


def test_readiness_when_unavailable(monkeypatch):
    from sqlalchemy import text
    from app.core.database import engine

    original_execute = engine.connect

    def failing_connect(*args, **kwargs):
        raise RuntimeError("Connection refused")

    monkeypatch.setattr(engine, "connect", failing_connect)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert "Database unavailable" in response.json()["detail"]