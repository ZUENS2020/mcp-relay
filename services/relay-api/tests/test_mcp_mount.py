"""MCP admin endpoint mounting and auth (mcp>=2.0.0 lifespan hoisting)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BASE_URL = "http://127.0.0.1:8740"


def _client(tmp_path: Path, monkeypatch, **extra_env):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    monkeypatch.setenv("RELAY_BASE_URL", "http://testserver")
    for k, v in extra_env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    # Reload mcp_server first so its module-level mount state resets between
    # tests, then reload main so it re-runs mount_mcp() with the new env.
    import app.mcp_server as mcp_server

    importlib.reload(mcp_server)
    import app.main as main

    importlib.reload(main)
    main.init_db()
    main._SESSIONS.clear()
    return main


@pytest.fixture()
def mcp_client(tmp_path, monkeypatch):
    """TestClient as context manager so the app lifespan (MCP session manager) runs."""
    main = _client(
        tmp_path,
        monkeypatch,
        RELAY_MCP_ADMIN_TOKEN="test-mcp-admin-token",
    )
    with TestClient(main.app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture()
def no_mcp_client(tmp_path, monkeypatch):
    """Admin token unset entirely -> mount_mcp() no-ops -> /mcp is 404."""
    main = _client(
        tmp_path,
        monkeypatch,
        RELAY_ADMIN_TOKEN=None,
        RELAY_MCP_ADMIN_TOKEN=None,
    )
    with TestClient(main.app, base_url=BASE_URL) as client:
        yield client


def _init_body():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }


def test_mcp_endpoint_mounted_with_token(mcp_client):
    """With RELAY_MCP_ADMIN_TOKEN set, /mcp exists and enforces Bearer auth."""
    body = _init_body()
    # No token -> 401 (auth middleware fires before MCP app).
    assert mcp_client.post("/mcp", json=body).status_code == 401
    # Wrong token -> 401
    assert (
        mcp_client.post(
            "/mcp",
            json=body,
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code
        == 401
    )
    # Correct token -> MCP app responds (not 404/401).
    ok = mcp_client.post(
        "/mcp",
        json=body,
        headers={"Authorization": "Bearer test-mcp-admin-token"},
    )
    assert ok.status_code == 200
    assert "mcp-relay" in ok.text


def test_mcp_endpoint_not_mounted_without_token(no_mcp_client):
    """Without any admin token, /mcp is not mounted (404)."""
    resp = no_mcp_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert resp.status_code == 404
