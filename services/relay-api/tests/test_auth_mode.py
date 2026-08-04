"""Auth mode: password (default) vs access (reverse-proxy gated)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path: Path, monkeypatch, **extra_env):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    for k, v in extra_env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    import app.mcp_server as mcp_server

    importlib.reload(mcp_server)
    import app.main as main

    importlib.reload(main)
    main.init_db()
    main._SESSIONS.clear()
    return main


@pytest.fixture()
def password_client(tmp_path, monkeypatch):
    main = _client(tmp_path, monkeypatch, RELAY_AUTH_MODE="password")
    with TestClient(main.app) as client:
        yield client


@pytest.fixture()
def access_client(tmp_path, monkeypatch):
    main = _client(tmp_path, monkeypatch, RELAY_AUTH_MODE="access")
    with TestClient(main.app) as client:
        yield client


def test_auth_config_default_password(tmp_path, monkeypatch):
    main = _client(tmp_path, monkeypatch)  # no env override -> default
    with TestClient(main.app) as client:
        cfg = client.get("/api/v1/auth/config")
        assert cfg.status_code == 200
        assert cfg.json()["mode"] == "password"
        assert cfg.json()["login_available"] is True


def test_auth_config_access(tmp_path, monkeypatch):
    main = _client(tmp_path, monkeypatch, RELAY_AUTH_MODE="access")
    with TestClient(main.app) as client:
        cfg = client.get("/api/v1/auth/config")
        assert cfg.status_code == 200
        assert cfg.json()["mode"] == "access"
        assert cfg.json()["login_available"] is False


def test_password_mode_requires_login(password_client):
    assert password_client.get("/api/v1/devices").status_code == 401
    assert password_client.get("/api/v1/audit").status_code == 401
    # login works
    login = password_client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    assert (
        password_client.get(
            "/api/v1/devices",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 200
    )


def test_access_mode_open_admin_api(access_client):
    """In access mode the reverse proxy is the gate; admin API is open."""
    assert access_client.get("/api/v1/devices").status_code == 200
    assert access_client.get("/api/v1/audit").status_code == 200
    # login endpoint still exists but is not required
    assert (
        access_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"},
        ).status_code
        == 401
    )
