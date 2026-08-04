"""Bootstrap local mcp into empty device agent config."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    # import after env so DB_PATH resolves correctly
    import importlib

    import app.main as main

    importlib.reload(main)
    main.init_db()
    return TestClient(main.app), main


def test_bootstrap_writes_when_empty(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-boot-1",
            "profile": "windows-desktop",
            "targets": ["cursor"],
            "hostname": "test-host",
        },
    )
    assert reg.status_code == 200, reg.text
    token = reg.json()["device_token"]

    body = {
        "mcp_document": {
            "mcpServers": {
                "trek": {"url": "https://example.com/mcp", "type": "http"},
            }
        }
    }
    r = client.post(
        "/api/v1/devices/me/agents/cursor/bootstrap",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ok"
    assert data["server_count"] == 1
    assert "trek" in data["servers"]

    detail = client.get(f"/api/v1/devices/{reg.json()['device_id']}")
    assert detail.status_code == 200
    ac = detail.json()["agent_config"]["cursor"]
    assert ac["mcp_servers"]["trek"]["url"] == "https://example.com/mcp"


def test_bootstrap_skips_when_already_configured(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-boot-2",
            "profile": "windows-desktop",
            "targets": ["cursor"],
        },
    )
    token = reg.json()["device_token"]
    headers = {"Authorization": f"Bearer {token}"}
    first = {
        "mcp_document": {"mcpServers": {"a": {"url": "https://a.example"}}},
    }
    assert client.post("/api/v1/devices/me/agents/cursor/bootstrap", json=first, headers=headers).json()["status"] == "ok"
    second = {
        "mcp_document": {"mcpServers": {"b": {"url": "https://b.example"}}},
    }
    r = client.post("/api/v1/devices/me/agents/cursor/bootstrap", json=second, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"
    assert r.json()["reason"] == "already_configured"


def test_register_unions_detected_targets(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-union-1",
            "profile": "windows-desktop",
            "targets": ["pi"],
            "detected": [
                {"id": "cursor", "path": "C:\\Users\\x\\.cursor\\mcp.json", "present": True},
                {"id": "pi", "path": "C:\\Users\\x\\.pi\\agent\\mcp.json", "present": True},
                {"id": "codex", "path": "C:\\Users\\x\\.codex\\config.toml", "present": True},
            ],
        },
    )
    assert reg.status_code == 200, reg.text
    targets = reg.json()["targets"]
    assert "pi" in targets
    assert "cursor" in targets
    assert "codex" in targets



    # minimal runner without pytest
    import tempfile
    from unittest.mock import MagicMock

    class MP:
        def __init__(self):
            self._env = {}

        def setenv(self, k, v):
            self._env[k] = os.environ.get(k)
            os.environ[k] = v

        def undo(self):
            for k, v in self._env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    with tempfile.TemporaryDirectory() as td:
        mp = MP()
        try:
            test_bootstrap_writes_when_empty(Path(td) / "a", mp)
            mp.undo()
            test_bootstrap_skips_when_already_configured(Path(td) / "b", mp)
            print("ok")
        finally:
            mp.undo()
