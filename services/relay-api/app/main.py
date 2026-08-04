"""MCP Relay API — configuration control plane."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

TARGETS = ("cursor", "hermes", "pi", "codex", "claude-code")
PROFILES = ("windows-desktop", "mac-laptop", "nec-server")

DATA_DIR = Path(os.environ.get("RELAY_DATA", "/data")).resolve()
DB_PATH = DATA_DIR / "relay.db"

def _default_repo(name: str) -> Path:
    # Prefer env; fall back to repo layout when running from source checkout.
    for base in Path(__file__).resolve().parents:
        cand = base / name
        if cand.exists():
            return cand
    return Path(name)

CONFIG_REPO = Path(os.environ.get("RELAY_CONFIG_REPO", str(_default_repo("config-repo"))))
SKILLS_ROOT = Path(os.environ.get("SKILLS_ROOT", str(_default_repo("skills-repo"))))


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS logical_servers (
              id TEXT PRIMARY KEY,
              display_name TEXT,
              transport TEXT NOT NULL,
              default_json TEXT NOT NULL,
              tags_json TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS bindings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              logical_id TEXT NOT NULL,
              profile TEXT NOT NULL,
              target TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              overrides_json TEXT DEFAULT '{}',
              UNIQUE(logical_id, profile, target)
            );
            CREATE TABLE IF NOT EXISTS skill_packs (
              id TEXT PRIMARY KEY,
              version TEXT NOT NULL,
              path TEXT NOT NULL,
              targets_json TEXT NOT NULL,
              profiles_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
              device_id TEXT PRIMARY KEY,
              device_token TEXT NOT NULL,
              profile TEXT NOT NULL,
              targets_json TEXT NOT NULL,
              hostname TEXT,
              agent_version TEXT,
              last_sync_at TEXT,
              last_release_id TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS releases (
              id TEXT PRIMARY KEY,
              changelog TEXT,
              created_at TEXT NOT NULL,
              etag TEXT NOT NULL,
              artifact_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_reports (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              device_id TEXT NOT NULL,
              release_id TEXT,
              ok INTEGER NOT NULL,
              detail_json TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              action TEXT NOT NULL,
              detail_json TEXT,
              created_at TEXT NOT NULL
            );
            """
        )


def seed_from_config_repo() -> None:
    """Load YAML/JSON samples from config-repo if tables empty."""
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM logical_servers").fetchone()["c"]
        need_logical = n == 0
        need_skills = conn.execute("SELECT COUNT(*) AS c FROM skill_packs").fetchone()["c"] == 0

    if need_logical:
        logical_dir = CONFIG_REPO / "logical-servers"
        bindings_file = CONFIG_REPO / "bindings" / "bindings.json"
        if logical_dir.exists():
            for p in sorted(logical_dir.glob("*.json")):
                data = json.loads(p.read_text(encoding="utf-8"))
                with db() as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO logical_servers(id, display_name, transport, default_json, tags_json) VALUES (?,?,?,?,?)",
                        (
                            data["id"],
                            data.get("display_name", data["id"]),
                            data["transport"],
                            json.dumps(data.get("default", {})),
                            json.dumps(data.get("tags", [])),
                        ),
                    )
        if bindings_file.exists():
            items = json.loads(bindings_file.read_text(encoding="utf-8"))
            with db() as conn:
                for b in items:
                    conn.execute(
                        "INSERT OR IGNORE INTO bindings(logical_id, profile, target, enabled, overrides_json) VALUES (?,?,?,?,?)",
                        (
                            b["logical_id"],
                            b["profile"],
                            b["target"],
                            1 if b.get("enabled", True) else 0,
                            json.dumps(b.get("overrides", {})),
                        ),
                    )

    if need_skills:
        skills_manifest = SKILLS_ROOT / "manifest.json"
        if skills_manifest.exists():
            packs = json.loads(skills_manifest.read_text(encoding="utf-8"))
            if isinstance(packs, dict):
                packs = [packs]
            with db() as conn:
                for pack in packs:
                    conn.execute(
                        "INSERT OR REPLACE INTO skill_packs(id, version, path, targets_json, profiles_json) VALUES (?,?,?,?,?)",
                        (
                            pack["id"],
                            pack["version"],
                            pack["path"],
                            json.dumps(pack.get("targets", {})),
                            json.dumps(pack.get("profiles", list(PROFILES))),
                        ),
                    )


def merge_server(logical: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    out = dict(logical.get("default") or {})
    for k, v in (overrides or {}).items():
        if k == "env" and isinstance(v, dict):
            env = dict(out.get("env") or {})
            env.update(v)
            out["env"] = env
        elif k == "headers" and isinstance(v, dict):
            headers = dict(out.get("headers") or {})
            headers.update(v)
            out["headers"] = headers
        else:
            out[k] = v
    return out


def build_artifact(profile: str, targets: list[str]) -> dict[str, Any]:
    with db() as conn:
        logicals = {
            r["id"]: {
                "id": r["id"],
                "display_name": r["display_name"],
                "transport": r["transport"],
                "default": json.loads(r["default_json"]),
                "tags": json.loads(r["tags_json"] or "[]"),
            }
            for r in conn.execute("SELECT * FROM logical_servers").fetchall()
        }
        bindings = [dict(r) for r in conn.execute("SELECT * FROM bindings WHERE profile=?", (profile,)).fetchall()]
        packs = [dict(r) for r in conn.execute("SELECT * FROM skill_packs").fetchall()]

    by_target: dict[str, dict[str, Any]] = {t: {} for t in targets if t in TARGETS}
    for b in bindings:
        t = b["target"]
        if t not in by_target:
            continue
        if not b["enabled"]:
            continue
        lid = b["logical_id"]
        if lid not in logicals:
            continue
        by_target[t][lid] = merge_server(logicals[lid], json.loads(b["overrides_json"] or "{}"))

    skill_out = []
    for p in packs:
        profiles = json.loads(p["profiles_json"] or "[]")
        if profile not in profiles and profiles:
            continue
        tmap = json.loads(p["targets_json"] or "{}")
        skill_out.append(
            {
                "id": p["id"],
                "version": p["version"],
                "path": p["path"],
                "targets": {k: v for k, v in tmap.items() if k in by_target or not targets},
            }
        )

    return {
        "profile": profile,
        "targets": by_target,
        "skills": skill_out,
        "built_at": utcnow(),
    }


app = FastAPI(title="MCP Relay", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()
    seed_from_config_repo()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utcnow()}


# --- Auth helpers ---


def require_device(
    authorization: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> sqlite3.Row:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if x_device_token:
        token = x_device_token
    if not token:
        raise HTTPException(401, "device token required")
    with db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "invalid device token")
    return row


# --- Agent API ---


class RegisterRequest(BaseModel):
    device_id: str | None = None
    profile: str
    targets: list[str] = Field(default_factory=list)
    hostname: str | None = None
    agent_version: str = "0.1.0"


@app.post("/api/v1/devices/register")
def register_device(body: RegisterRequest) -> dict[str, Any]:
    if body.profile not in PROFILES:
        raise HTTPException(400, f"invalid profile: {body.profile}")
    targets = [t for t in body.targets if t in TARGETS]
    device_id = body.device_id or f"{body.profile}-{secrets.token_hex(6)}"
    token = secrets.token_urlsafe(32)
    with db() as conn:
        existing = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE devices SET profile=?, targets_json=?, hostname=?, agent_version=? WHERE device_id=?",
                (body.profile, json.dumps(targets), body.hostname, body.agent_version, device_id),
            )
            token = existing["device_token"]
        else:
            conn.execute(
                "INSERT INTO devices(device_id, device_token, profile, targets_json, hostname, agent_version, created_at) VALUES (?,?,?,?,?,?,?)",
                (device_id, token, body.profile, json.dumps(targets), body.hostname, body.agent_version, utcnow()),
            )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("device.register", json.dumps({"device_id": device_id, "targets": targets}), utcnow()),
        )
    return {"device_id": device_id, "device_token": token, "profile": body.profile, "targets": targets}


@app.get("/api/v1/devices/me")
def device_me(device: sqlite3.Row = Depends(require_device)) -> dict[str, Any]:
    return {
        "device_id": device["device_id"],
        "profile": device["profile"],
        "targets": json.loads(device["targets_json"] or "[]"),
        "hostname": device["hostname"],
        "agent_version": device["agent_version"],
        "last_sync_at": device["last_sync_at"],
        "last_release_id": device["last_release_id"],
    }


@app.get("/api/v1/releases/latest")
def latest_release(
    profile: str = Query(...),
    targets: str = Query(""),
    device: sqlite3.Row = Depends(require_device),
) -> dict[str, Any]:
    tlist = [t.strip() for t in targets.split(",") if t.strip()] or json.loads(device["targets_json"] or "[]")
    artifact = build_artifact(profile, tlist)
    etag = secrets.token_hex(8)
    # reuse latest if identical profile+targets content
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM releases ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if row:
            prev = json.loads(row["artifact_json"])
            if prev.get("profile") == profile and prev.get("targets") == artifact["targets"] and prev.get("skills") == artifact["skills"]:
                return {"id": row["id"], "etag": row["etag"], "created_at": row["created_at"], "changelog": row["changelog"], "artifact": prev}

        rid = f"rel-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{etag[:4]}"
        conn.execute(
            "INSERT INTO releases(id, changelog, created_at, etag, artifact_json) VALUES (?,?,?,?,?)",
            (rid, "auto", utcnow(), etag, json.dumps(artifact)),
        )
    return {"id": rid, "etag": etag, "created_at": utcnow(), "changelog": "auto", "artifact": artifact}


@app.get("/api/v1/releases/{release_id}/bundle")
def release_bundle(release_id: str, device: sqlite3.Row = Depends(require_device)) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if not row:
        raise HTTPException(404, "release not found")
    return {"id": row["id"], "etag": row["etag"], "artifact": json.loads(row["artifact_json"])}


@app.get("/api/v1/releases/{release_id}/render/{target}")
def render_target(release_id: str, target: str, device: sqlite3.Row = Depends(require_device)) -> dict[str, Any]:
    if target not in TARGETS:
        raise HTTPException(400, "invalid target")
    with db() as conn:
        row = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
    if not row:
        raise HTTPException(404, "release not found")
    art = json.loads(row["artifact_json"])
    return {"target": target, "servers": art.get("targets", {}).get(target, {})}


class SyncReport(BaseModel):
    release_id: str | None = None
    ok: bool = True
    detail: dict[str, Any] = Field(default_factory=dict)


@app.post("/api/v1/devices/me/sync-report")
def sync_report(body: SyncReport, device: sqlite3.Row = Depends(require_device)) -> dict[str, str]:
    with db() as conn:
        conn.execute(
            "INSERT INTO sync_reports(device_id, release_id, ok, detail_json, created_at) VALUES (?,?,?,?,?)",
            (device["device_id"], body.release_id, 1 if body.ok else 0, json.dumps(body.detail), utcnow()),
        )
        if body.ok and body.release_id:
            conn.execute(
                "UPDATE devices SET last_sync_at=?, last_release_id=? WHERE device_id=?",
                (utcnow(), body.release_id, device["device_id"]),
            )
    return {"status": "recorded"}


# --- Admin API (open for MVP; protect via CF Access in front) ---


class LogicalIn(BaseModel):
    id: str
    display_name: str | None = None
    transport: str
    default: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


@app.get("/api/v1/logical-servers")
def list_logical() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM logical_servers").fetchall()
    return [
        {
            "id": r["id"],
            "display_name": r["display_name"],
            "transport": r["transport"],
            "default": json.loads(r["default_json"]),
            "tags": json.loads(r["tags_json"] or "[]"),
        }
        for r in rows
    ]


@app.post("/api/v1/logical-servers")
def upsert_logical(body: LogicalIn) -> dict[str, str]:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO logical_servers(id, display_name, transport, default_json, tags_json) VALUES (?,?,?,?,?)",
            (body.id, body.display_name or body.id, body.transport, json.dumps(body.default), json.dumps(body.tags)),
        )
    return {"status": "ok"}


class BindingIn(BaseModel):
    logical_id: str
    profile: str
    target: str
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/v1/bindings")
def list_bindings() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM bindings").fetchall()
    return [
        {
            "id": r["id"],
            "logical_id": r["logical_id"],
            "profile": r["profile"],
            "target": r["target"],
            "enabled": bool(r["enabled"]),
            "overrides": json.loads(r["overrides_json"] or "{}"),
        }
        for r in rows
    ]


@app.post("/api/v1/bindings")
def upsert_binding(body: BindingIn) -> dict[str, str]:
    if body.profile not in PROFILES or body.target not in TARGETS:
        raise HTTPException(400, "invalid profile/target")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO bindings(logical_id, profile, target, enabled, overrides_json) VALUES (?,?,?,?,?)
            ON CONFLICT(logical_id, profile, target) DO UPDATE SET
              enabled=excluded.enabled, overrides_json=excluded.overrides_json
            """,
            (body.logical_id, body.profile, body.target, 1 if body.enabled else 0, json.dumps(body.overrides)),
        )
    return {"status": "ok"}


@app.post("/api/v1/releases")
def create_release(changelog: str = "manual") -> dict[str, Any]:
    # build for all profiles into one multi-artifact (agents still filter)
    combined = {p: build_artifact(p, list(TARGETS)) for p in PROFILES}
    etag = secrets.token_hex(8)
    rid = f"rel-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{etag[:4]}"
    with db() as conn:
        conn.execute(
            "INSERT INTO releases(id, changelog, created_at, etag, artifact_json) VALUES (?,?,?,?,?)",
            (rid, changelog, utcnow(), etag, json.dumps({"profiles": combined, "built_at": utcnow()})),
        )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("release.create", json.dumps({"id": rid}), utcnow()),
        )
    return {"id": rid, "etag": etag}


@app.get("/api/v1/devices")
def list_devices() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT device_id, profile, targets_json, hostname, agent_version, last_sync_at, last_release_id, created_at FROM devices").fetchall()
    return [
        {
            "device_id": r["device_id"],
            "profile": r["profile"],
            "targets": json.loads(r["targets_json"] or "[]"),
            "hostname": r["hostname"],
            "agent_version": r["agent_version"],
            "last_sync_at": r["last_sync_at"],
            "last_release_id": r["last_release_id"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/api/v1/releases/{release_id}/diff/{prev_id}")
def release_diff(release_id: str, prev_id: str) -> dict[str, Any]:
    with db() as conn:
        a = conn.execute("SELECT * FROM releases WHERE id=?", (release_id,)).fetchone()
        b = conn.execute("SELECT * FROM releases WHERE id=?", (prev_id,)).fetchone()
    if not a or not b:
        raise HTTPException(404, "release not found")
    return {
        "current": json.loads(a["artifact_json"]),
        "previous": json.loads(b["artifact_json"]),
    }


@app.get("/api/v1/skill-packs")
def list_skills() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM skill_packs").fetchall()
    return [
        {
            "id": r["id"],
            "version": r["version"],
            "path": r["path"],
            "targets": json.loads(r["targets_json"] or "{}"),
            "profiles": json.loads(r["profiles_json"] or "[]"),
        }
        for r in rows
    ]


@app.get("/api/v1/audit")
def list_audit(limit: int = 50) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, action, detail_json, created_at FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": r["id"], "action": r["action"], "detail": json.loads(r["detail_json"] or "{}"), "created_at": r["created_at"]}
        for r in rows
    ]


@app.get("/", response_class=HTMLResponse)
def admin_ui() -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>MCP Relay</title>
<style>
body{font-family:system-ui,sans-serif;margin:2rem;background:#0f1419;color:#e7ecf1}
a{color:#6cb6ff} .card{background:#1a2332;padding:1rem 1.25rem;border-radius:8px;margin:1rem 0}
code{background:#243044;padding:0.1rem 0.35rem;border-radius:4px}
</style></head>
<body>
<h1>MCP Relay</h1>
<p>Config control plane · targets: cursor · hermes · pi · codex · claude-code</p>
<div class="card"><h3>Health</h3><pre id="h">loading…</pre></div>
<div class="card"><h3>Logical servers</h3><pre id="l">loading…</pre></div>
<div class="card"><h3>Bindings</h3><pre id="b">loading…</pre></div>
<div class="card"><h3>Devices</h3><pre id="d">loading…</pre></div>
<script>
async function j(u){const r=await fetch(u);return r.json()}
(async()=>{
  h.textContent=JSON.stringify(await j('/health'),null,2);
  l.textContent=JSON.stringify(await j('/api/v1/logical-servers'),null,2);
  b.textContent=JSON.stringify(await j('/api/v1/bindings'),null,2);
  d.textContent=JSON.stringify(await j('/api/v1/devices'),null,2);
})()
</script>
</body></html>"""
