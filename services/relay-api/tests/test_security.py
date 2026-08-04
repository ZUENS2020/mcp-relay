"""Admin auth and register token-theft protections."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


ADMIN = "test-admin-token-please-change"


def _client(tmp_path: Path, monkeypatch, **extra_env):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    monkeypatch.setenv("RELAY_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("RELAY_MCP_ADMIN_TOKEN", raising=False)
    for k, v in extra_env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import importlib

    import app.main as main

    importlib.reload(main)
    main.init_db()
    main._SESSIONS.clear()
    return TestClient(main.app), main


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN}"}


def test_admin_api_requires_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    assert client.get("/api/v1/devices").status_code == 401
    assert client.get("/api/v1/devices", headers=_admin_headers()).status_code == 200


def test_password_login_issues_session(tmp_path, monkeypatch):
    client, _ = _client(
        tmp_path,
        monkeypatch,
        RELAY_ADMIN_USER="admin",
        RELAY_ADMIN_PASSWORD="admin123",
    )
    bad = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert ok.status_code == 200, ok.text
    token = ok.json()["token"]
    assert token
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"] == "admin"
    assert me.json()["auth"] == "session"
    assert client.get("/api/v1/devices", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert client.get("/api/v1/devices", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_login_works_without_admin_token(tmp_path, monkeypatch):
    """UI password login must work even when RELAY_ADMIN_TOKEN is unset."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    monkeypatch.delenv("RELAY_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("RELAY_MCP_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("RELAY_ADMIN_USER", "admin")
    monkeypatch.setenv("RELAY_ADMIN_PASSWORD", "admin123")
    import importlib

    import app.main as main

    importlib.reload(main)
    main.init_db()
    main._SESSIONS.clear()
    client = TestClient(main.app)

    assert client.get("/api/v1/devices").status_code == 401
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin123"})
    assert login.status_code == 200
    token = login.json()["token"]
    assert client.get("/api/v1/devices", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_register_does_not_leak_existing_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={"device_id": "sec-dev-1", "profile": "windows-desktop", "targets": ["cursor"]},
    )
    assert reg.status_code == 200
    token = reg.json()["device_token"]

    # Attacker knows device_id but not token
    steal = client.post(
        "/api/v1/devices/register",
        json={"device_id": "sec-dev-1", "profile": "windows-desktop", "targets": ["cursor"]},
    )
    assert steal.status_code == 409
    assert "device_token" not in steal.json() or steal.json().get("device_token") != token

    # Owner refresh with bearer succeeds and keeps same token
    refresh = client.post(
        "/api/v1/devices/register",
        json={"device_id": "sec-dev-1", "profile": "windows-desktop", "targets": ["cursor", "pi"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert refresh.status_code == 200
    assert refresh.json()["device_token"] == token
    assert "pi" in refresh.json()["targets"]


def test_patch_requires_admin(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={"device_id": "sec-dev-2", "profile": "windows-desktop", "targets": ["cursor"]},
    )
    device_id = reg.json()["device_id"]
    denied = client.patch(
        f"/api/v1/devices/{device_id}/agents",
        json={"agent_config": {"cursor": {"enabled": True, "mcp_document": {"mcpServers": {}}}}},
    )
    assert denied.status_code == 401
    ok = client.patch(
        f"/api/v1/devices/{device_id}/agents",
        json={"agent_config": {"cursor": {"enabled": True, "mcp_document": {"mcpServers": {"x": {"url": "https://x"}}}}}},
        headers=_admin_headers(),
    )
    assert ok.status_code == 200, ok.text
