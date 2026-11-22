"""健康检查契约。"""
from __future__ import annotations


def test_health_returns_envelope(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["version"]
    assert body["data"]["static_dir_exists"] is True
    assert "db" in body["data"]
    assert "X-Request-ID" in resp.headers


def test_ready_endpoint(client):
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code == 200
    assert resp.json()["data"]["ready"] is True
