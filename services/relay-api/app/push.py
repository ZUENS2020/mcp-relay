"""Push delivery tracking and WebSocket dispatch."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .hub import ConnectionHub


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


PUSH_STATUSES = ("queued", "sent", "acked", "failed", "expired")


def init_push_table(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS push_deliveries (
          id TEXT PRIMARY KEY,
          device_id TEXT NOT NULL,
          release_id TEXT NOT NULL,
          targets_json TEXT NOT NULL,
          trigger TEXT NOT NULL,
          trigger_detail_json TEXT DEFAULT '{}',
          status TEXT NOT NULL,
          error TEXT,
          created_at TEXT NOT NULL,
          sent_at TEXT,
          acked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_push_device_created
          ON push_deliveries(device_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_push_status
          ON push_deliveries(status, device_id);
        """
    )


def delivery_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "device_id": r["device_id"],
        "release_id": r["release_id"],
        "targets": json.loads(r["targets_json"] or "[]"),
        "trigger": r["trigger"],
        "trigger_detail": json.loads(r["trigger_detail_json"] or "{}"),
        "status": r["status"],
        "error": r["error"],
        "created_at": r["created_at"],
        "sent_at": r["sent_at"],
        "acked_at": r["acked_at"],
    }


def create_delivery(
    conn: sqlite3.Connection,
    *,
    device_id: str,
    release_id: str,
    targets: list[str],
    trigger: str,
    trigger_detail: dict[str, Any] | None = None,
    status: str = "queued",
) -> dict[str, Any]:
    did = f"push-{secrets.token_hex(8)}"
    now = utcnow()
    conn.execute(
        """INSERT INTO push_deliveries
           (id, device_id, release_id, targets_json, trigger, trigger_detail_json,
            status, error, created_at, sent_at, acked_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            did,
            device_id,
            release_id,
            json.dumps(targets),
            trigger,
            json.dumps(trigger_detail or {}),
            status,
            None,
            now,
            None,
            None,
        ),
    )
    row = conn.execute("SELECT * FROM push_deliveries WHERE id=?", (did,)).fetchone()
    assert row is not None
    return delivery_dict(row)


def update_delivery(
    conn: sqlite3.Connection,
    delivery_id: str,
    *,
    status: str,
    error: str | None = None,
    sent: bool = False,
    acked: bool = False,
) -> None:
    now = utcnow()
    row = conn.execute("SELECT * FROM push_deliveries WHERE id=?", (delivery_id,)).fetchone()
    if not row:
        return
    sent_at = row["sent_at"] or (now if sent else None)
    acked_at = row["acked_at"] or (now if acked else None)
    conn.execute(
        """UPDATE push_deliveries SET status=?, error=?, sent_at=?, acked_at=? WHERE id=?""",
        (status, error, sent_at, acked_at, delivery_id),
    )


def list_deliveries(
    conn: sqlite3.Connection,
    *,
    device_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    if device_id:
        rows = conn.execute(
            """SELECT * FROM push_deliveries WHERE device_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (device_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM push_deliveries ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [delivery_dict(r) for r in rows]


def pending_count(conn: sqlite3.Connection, device_id: str) -> int:
    row = conn.execute(
        """SELECT COUNT(*) AS c FROM push_deliveries
           WHERE device_id=? AND status IN ('queued','sent')""",
        (device_id,),
    ).fetchone()
    return int(row["c"]) if row else 0


def last_push_summary(conn: sqlite3.Connection, device_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT * FROM push_deliveries WHERE device_id=?
           ORDER BY created_at DESC LIMIT 1""",
        (device_id,),
    ).fetchone()
    if not row:
        return None
    d = delivery_dict(row)
    return {"id": d["id"], "status": d["status"], "created_at": d["created_at"], "error": d["error"]}


def pending_deliveries(conn: sqlite3.Connection, device_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT * FROM push_deliveries WHERE device_id=? AND status='queued'
           ORDER BY created_at ASC""",
        (device_id,),
    ).fetchall()
    return [delivery_dict(r) for r in rows]


def create_release_for_device(
    conn: sqlite3.Connection,
    device_row: sqlite3.Row,
    *,
    build_artifact_for_device,
    changelog: str = "push",
) -> tuple[str, dict[str, Any]]:
    """Build artifact and persist release. Returns (release_id, artifact)."""
    artifact = build_artifact_for_device(device_row)
    etag = secrets.token_hex(8)
    device_id = device_row["device_id"]
    rid = f"rel-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{etag[:4]}"
    artifact["device_id"] = device_id
    conn.execute(
        "INSERT INTO releases(id, changelog, created_at, etag, artifact_json) VALUES (?,?,?,?,?)",
        (rid, changelog, utcnow(), etag, json.dumps(artifact)),
    )
    return rid, artifact


async def send_delivery(hub: "ConnectionHub", conn: sqlite3.Connection, delivery: dict[str, Any]) -> bool:
    ok = await hub.send_json(
        delivery["device_id"],
        {
            "type": "push.apply",
            "delivery_id": delivery["id"],
            "release_id": delivery["release_id"],
            "targets": delivery["targets"],
        },
    )
    if ok:
        update_delivery(conn, delivery["id"], status="sent", sent=True)
    return ok


async def enqueue_push(
    hub: "ConnectionHub",
    conn: sqlite3.Connection,
    *,
    device_id: str,
    device_row: sqlite3.Row,
    targets: list[str],
    trigger: str,
    trigger_detail: dict[str, Any] | None,
    build_artifact_for_device,
) -> dict[str, Any]:
    release_id, _ = create_release_for_device(
        conn, device_row, build_artifact_for_device=build_artifact_for_device, changelog=trigger
    )
    delivery = create_delivery(
        conn,
        device_id=device_id,
        release_id=release_id,
        targets=targets,
        trigger=trigger,
        trigger_detail=trigger_detail,
        status="queued",
    )
    sent = await send_delivery(hub, conn, delivery)
    if not sent:
        delivery["status"] = "queued"
    else:
        delivery["status"] = "sent"
        delivery["sent_at"] = utcnow()
    return delivery


async def flush_pending(
    hub: "ConnectionHub",
    conn: sqlite3.Connection,
    device_id: str,
) -> int:
    if not hub.is_online(device_id):
        return 0
    n = 0
    for d in pending_deliveries(conn, device_id):
        if await send_delivery(hub, conn, d):
            n += 1
    return n


def record_push_ack(
    conn: sqlite3.Connection,
    *,
    delivery_id: str,
    ok: bool,
    detail: dict[str, Any] | None = None,
    device_id: str | None = None,
) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM push_deliveries WHERE id=?", (delivery_id,)).fetchone()
    if not row:
        return None
    if device_id and row["device_id"] != device_id:
        return None
    status = "acked" if ok else "failed"
    err = None if ok else str((detail or {}).get("error") or "apply failed")
    update_delivery(conn, delivery_id, status=status, error=err, acked=True)
    conn.execute(
        "INSERT INTO sync_reports(device_id, release_id, ok, detail_json, created_at) VALUES (?,?,?,?,?)",
        (
            row["device_id"],
            row["release_id"],
            1 if ok else 0,
            json.dumps({"push_delivery_id": delivery_id, **(detail or {})}),
            utcnow(),
        ),
    )
    if ok:
        conn.execute(
            "UPDATE devices SET last_sync_at=?, last_release_id=?, last_seen_at=? WHERE device_id=?",
            (utcnow(), row["release_id"], utcnow(), row["device_id"]),
        )
    return delivery_dict(
        conn.execute("SELECT * FROM push_deliveries WHERE id=?", (delivery_id,)).fetchone()
    )
