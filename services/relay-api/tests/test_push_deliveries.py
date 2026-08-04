"""Push delivery and WebSocket tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


ADMIN = "test-admin-token-please-change"


def _client(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RELAY_DATA", str(data))
    monkeypatch.setenv("RELAY_ADMIN_TOKEN", ADMIN)
    monkeypatch.delenv("RELAY_MCP_ADMIN_TOKEN", raising=False)
    import importlib

    import app.main as main

    importlib.reload(main)
    main.init_db()
    return TestClient(main.app), main


def _admin():
    return {"Authorization": f"Bearer {ADMIN}"}


def test_patch_creates_push_delivery(tmp_path, monkeypatch):
    client, _main = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={"device_id": "push-test-1", "profile": "nec-server", "targets": ["cursor"]},
    )
    assert reg.status_code == 200
    device_id = reg.json()["device_id"]

    patch = {
        "agent_config": {
            "cursor": {
                "enabled": True,
                "mcp_document": {"mcpServers": {"demo": {"url": "https://example.com"}}},
            }
        }
    }
    r = client.patch(f"/api/v1/devices/{device_id}/agents", json=patch, headers=_admin())
    assert r.status_code == 200, r.text

    deliveries = client.get("/api/v1/push-deliveries", params={"device_id": device_id}, headers=_admin())
    assert deliveries.status_code == 200
    items = deliveries.json()
    assert len(items) >= 1
    assert items[0]["status"] in ("queued", "sent")
    assert items[0]["device_id"] == device_id

    devices = client.get("/api/v1/devices", headers=_admin()).json()
    dev = next(d for d in devices if d["device_id"] == device_id)
    assert dev["online"] is False
    assert dev["pending_push_count"] >= 1
    assert dev["last_push"] is not None


def test_ws_ack_marks_delivery(tmp_path, monkeypatch):
    client, _main = _client(tmp_path, monkeypatch)
    reg = client.post(
        "/api/v1/devices/register",
        json={"device_id": "push-test-2", "profile": "nec-server", "targets": ["cursor"]},
    )
    token = reg.json()["device_token"]
    device_id = reg.json()["device_id"]

    client.patch(
        f"/api/v1/devices/{device_id}/agents",
        headers=_admin(),
        json={
            "agent_config": {
                "cursor": {"mcp_document": {"mcpServers": {"x": {"url": "https://x.example"}}}}
            }
        },
    )
    delivery_id = client.get(
        "/api/v1/push-deliveries", params={"device_id": device_id}, headers=_admin()
    ).json()[0]["id"]

    # Prefer Authorization header (no token in query).
    with client.websocket_connect("/api/v1/devices/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "connected"
        flushed = ws.receive_json()
        if flushed["type"] == "push.apply":
            assert flushed["delivery_id"] == delivery_id
            ws.send_json({"type": "push.ack", "delivery_id": delivery_id, "ok": True, "detail": {}})
            ack = ws.receive_json()
            assert ack["type"] == "push.ack.received"
        else:
            ws.send_json({"type": "push.ack", "delivery_id": delivery_id, "ok": True, "detail": {}})
            assert flushed["type"] == "push.ack.received"

    updated = client.get(
        "/api/v1/push-deliveries", params={"device_id": device_id}, headers=_admin()
    ).json()[0]
    assert updated["status"] == "acked"
