"""Bootstrap local mcp into empty device agent config."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    monkeypatch.setenv("RELAY_ADMIN_TOKEN", "test-admin-token-please-change")
    # import after env so DB_PATH resolves correctly
    import importlib

    import app.main as main

    importlib.reload(main)
    main.init_db()
    return TestClient(main.app), main


def _admin():
    return {"Authorization": "Bearer test-admin-token-please-change"}


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

    detail = client.get(f"/api/v1/devices/{reg.json()['device_id']}", headers=_admin())
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


def test_delete_device_revokes_token(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-del-1",
            "profile": "windows-desktop",
            "targets": ["cursor"],
            "hostname": "bye",
        },
    )
    assert reg.status_code == 200
    token = reg.json()["device_token"]
    device_id = reg.json()["device_id"]

    assert client.get("/api/v1/devices/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    deleted = client.delete(f"/api/v1/devices/{device_id}", headers=_admin())
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get(f"/api/v1/devices/{device_id}", headers=_admin()).status_code == 404
    assert client.get("/api/v1/devices/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_patch_mcp_document_twice_keeps_latest(tmp_path, monkeypatch):
    """Regression: second admin save must replace the pinned document, not revert."""
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-patch-2x",
            "profile": "windows-desktop",
            "targets": ["cursor"],
        },
    )
    assert reg.status_code == 200
    device_id = reg.json()["device_id"]

    first = client.patch(
        f"/api/v1/devices/{device_id}/agents",
        headers=_admin(),
        json={
            "agent_config": {
                "cursor": {
                    "enabled": True,
                    "mcp_document": {"mcpServers": {"one": {"url": "https://one.example"}}},
                }
            }
        },
    )
    assert first.status_code == 200, first.text
    agent = next(a for a in first.json()["agents"] if a["id"] == "cursor")
    assert agent["mcp_document"]["mcpServers"]["one"]["url"] == "https://one.example"

    second = client.patch(
        f"/api/v1/devices/{device_id}/agents",
        headers=_admin(),
        json={
            "agent_config": {
                "cursor": {
                    "enabled": True,
                    "mcp_document": {
                        "mcpServers": {
                            "one": {"url": "https://one.example"},
                            "two": {"url": "https://two.example"},
                        }
                    },
                }
            }
        },
    )
    assert second.status_code == 200, second.text
    agent2 = next(a for a in second.json()["agents"] if a["id"] == "cursor")
    assert set(agent2["mcp_document"]["mcpServers"]) == {"one", "two"}
    assert agent2["mcp_document"]["mcpServers"]["two"]["url"] == "https://two.example"

    detail = client.get(f"/api/v1/devices/{device_id}", headers=_admin())
    assert detail.status_code == 200
    pinned = detail.json()["agent_config"]["cursor"]["mcp_servers"]
    assert set(pinned) == {"one", "two"}


def test_bootstrap_does_not_overwrite_admin_save(tmp_path, monkeypatch):
    """First admin save must survive a subsequent agent bootstrap of local mcp."""
    client, _ = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-race-1",
            "profile": "windows-desktop",
            "targets": ["cursor"],
        },
    )
    assert reg.status_code == 200
    device_id = reg.json()["device_id"]
    token = reg.json()["device_token"]

    saved = client.patch(
        f"/api/v1/devices/{device_id}/agents",
        headers=_admin(),
        json={
            "agent_config": {
                "cursor": {
                    "enabled": True,
                    "mcp_document": {"mcpServers": {"admin": {"url": "https://admin.example"}}},
                }
            }
        },
    )
    assert saved.status_code == 200, saved.text

    boot = client.post(
        "/api/v1/devices/me/agents/cursor/bootstrap",
        headers={"Authorization": f"Bearer {token}"},
        json={"mcp_document": {"mcpServers": {"local": {"url": "https://local.example"}}}},
    )
    assert boot.status_code == 200
    assert boot.json()["status"] == "skipped"

    detail = client.get(f"/api/v1/devices/{device_id}", headers=_admin())
    pinned = detail.json()["agent_config"]["cursor"]["mcp_servers"]
    assert set(pinned) == {"admin"}
    assert "local" not in pinned


def test_artifact_uses_pinned_only_not_bindings(tmp_path, monkeypatch):
    """Release/sync artifact must come from pinned mcp_servers, not Profile bindings."""
    client, main = _client(tmp_path, monkeypatch)
    # Seed a binding that would previously leak into empty agents.
    with main.db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO logical_servers(id, display_name, transport, default_json, tags_json) VALUES (?,?,?,?,?)",
            ("from-binding", "From Binding", "http", '{"url":"https://binding.example"}', "[]"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO bindings(logical_id, profile, target, enabled, overrides_json) VALUES (?,?,?,?,?)",
            ("from-binding", "windows-desktop", "cursor", 1, "{}"),
        )

    reg = client.post(
        "/api/v1/devices/register",
        json={
            "device_id": "test-art-1",
            "profile": "windows-desktop",
            "targets": ["cursor"],
        },
    )
    device_id = reg.json()["device_id"]
    token = reg.json()["device_token"]

    # No pin yet → empty artifact target
    latest = client.get("/api/v1/releases/latest", headers={"Authorization": f"Bearer {token}"})
    assert latest.status_code == 200
    assert latest.json()["artifact"]["targets"].get("cursor", {}) == {}

    client.patch(
        f"/api/v1/devices/{device_id}/agents",
        headers=_admin(),
        json={
            "agent_config": {
                "cursor": {
                    "enabled": True,
                    "mcp_document": {"mcpServers": {"pinned": {"url": "https://pinned.example"}}},
                }
            }
        },
    )
    latest2 = client.get("/api/v1/releases/latest", headers={"Authorization": f"Bearer {token}"})
    cursor_servers = latest2.json()["artifact"]["targets"]["cursor"]
    assert set(cursor_servers) == {"pinned"}
    assert "from-binding" not in cursor_servers


if __name__ == "__main__":
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
