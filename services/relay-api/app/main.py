"""MCP Relay API — configuration control plane."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

TARGETS = ("cursor", "hermes", "pi", "codex", "claude-code")
PROFILES = ("windows-desktop", "mac-laptop", "linux-server")

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
              created_at TEXT NOT NULL,
              agent_config_json TEXT DEFAULT '{}',
              detected_json TEXT DEFAULT '[]',
              last_seen_at TEXT
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
        cols = {r[1] for r in conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "agent_config_json" not in cols:
            conn.execute("ALTER TABLE devices ADD COLUMN agent_config_json TEXT DEFAULT '{}'")
        if "detected_json" not in cols:
            conn.execute("ALTER TABLE devices ADD COLUMN detected_json TEXT DEFAULT '[]'")
        if "last_seen_at" not in cols:
            conn.execute("ALTER TABLE devices ADD COLUMN last_seen_at TEXT")
        from .push import init_push_table

        init_push_table(conn)


def enrich_device(d: dict[str, Any], conn: sqlite3.Connection) -> dict[str, Any]:
    from .hub import hub
    from .push import last_push_summary, pending_count

    out = dict(d)
    did = out["device_id"]
    out["online"] = hub.is_online(did)
    out["pending_push_count"] = pending_count(conn, did)
    out["last_push"] = last_push_summary(conn, did)
    return out


def device_dict(r: sqlite3.Row) -> dict[str, Any]:
    keys = set(r.keys())
    return {
        "device_id": r["device_id"],
        "profile": r["profile"],
        "targets": json.loads(r["targets_json"] or "[]"),
        "hostname": r["hostname"],
        "agent_version": r["agent_version"],
        "last_sync_at": r["last_sync_at"],
        "last_release_id": r["last_release_id"],
        "created_at": r["created_at"],
        "agent_config": json.loads(r["agent_config_json"] or "{}") if "agent_config_json" in keys else {},
        "detected": json.loads(r["detected_json"] or "[]") if "detected_json" in keys else [],
        "last_seen_at": r["last_seen_at"] if "last_seen_at" in keys else None,
    }


def filter_servers_for_agent(
    servers: dict[str, Any],
    agent_entry: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve servers for one agent. Pinned mcp_servers always wins; no Profile bindings."""
    if not agent_entry:
        return {}
    if agent_entry.get("enabled") is False:
        return {}
    pinned = agent_entry.get("mcp_servers")
    if isinstance(pinned, dict):
        return {str(k): (v if isinstance(v, dict) else {}) for k, v in pinned.items()}
    return {}


def build_artifact(profile: str, targets: list[str], agent_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Device/release artifact: only pinned per-agent mcp_servers (Profile bindings unused)."""
    agent_config = agent_config or {}
    by_target: dict[str, dict[str, Any]] = {}
    for t in targets:
        if t not in TARGETS:
            continue
        by_target[t] = filter_servers_for_agent({}, agent_config.get(t))
    return {
        "profile": profile,
        "targets": by_target,
        "skills": [],
        "built_at": utcnow(),
    }


def build_artifact_for_device(device: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    if isinstance(device, sqlite3.Row):
        d = device_dict(device)
    else:
        d = device
    return build_artifact(d["profile"], d["targets"], d.get("agent_config") or {})


def known_logical_ids() -> list[str]:
    with db() as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM logical_servers ORDER BY id").fetchall()]


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


STATIC_DIR = Path(__file__).resolve().parent / "static"


class NoCacheStaticFiles(StaticFiles):
    """Avoid Cloudflare/browser caching stale admin UI assets after deploy."""

    def file_response(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        return resp


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    seed_from_config_repo()
    # mcp>=2.0.0 needs its session-manager lifespan to run; Starlette mounts
    # skip child app lifespans, so we run it here.
    async with get_mcp_lifespan():
        yield


app = FastAPI(title="MCP Relay", version="0.2.4", lifespan=lifespan)
if STATIC_DIR.exists():
    app.mount("/static", NoCacheStaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": utcnow()}


class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/api/v1/auth/login")
def auth_login(body: LoginIn) -> dict[str, Any]:
    user = body.username.strip()
    if not (_token_ok(user, ADMIN_USER) and _token_ok(body.password, ADMIN_PASSWORD)):
        raise HTTPException(401, "invalid username or password")
    sess = _create_session(ADMIN_USER)
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("auth.login", json.dumps({"user": ADMIN_USER}), utcnow()),
        )
    return {"status": "ok", **sess}


@app.post("/api/v1/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)) -> dict[str, str]:
    got = _bearer_token(authorization)
    if got:
        _SESSIONS.pop(got, None)
    return {"status": "ok"}


@app.get("/api/v1/auth/config")
def auth_config() -> dict[str, Any]:
    """Expose auth mode so the frontend can skip the login gate in access mode."""
    return {"mode": AUTH_MODE, "login_available": AUTH_MODE == "password"}


@app.get("/api/v1/auth/me")
def auth_me(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    got = _bearer_token(authorization)
    if not got:
        raise HTTPException(401, "login required")
    sess = _session_valid(got)
    if sess:
        return {"user": sess["user"], "expires_at": sess["exp"], "auth": "session"}
    if ADMIN_TOKEN and _token_ok(got, ADMIN_TOKEN):
        return {"user": ADMIN_USER, "auth": "admin_token"}
    raise HTTPException(401, "invalid credentials")


@app.get("/")
def admin_ui() -> Response:
    index = STATIC_DIR / "index.html"
    if not index.exists():
        raise HTTPException(404, "frontend not found")
    html = index.read_text(encoding="utf-8")
    # In access mode the reverse proxy is the identity gate: render the login
    # gate hidden from the very first paint so it never flashes before the
    # frontend boot() confirms the mode.
    if AUTH_MODE == "access":
        html = html.replace(
            '<div id="login-gate" class="login-gate">',
            '<div id="login-gate" class="login-gate hidden">',
            1,
        )
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


ADMIN_TOKEN = (
    os.environ.get("RELAY_ADMIN_TOKEN") or os.environ.get("RELAY_MCP_ADMIN_TOKEN") or ""
).strip()
ADMIN_USER = (os.environ.get("RELAY_ADMIN_USER") or "admin").strip() or "admin"
ADMIN_PASSWORD = (os.environ.get("RELAY_ADMIN_PASSWORD") or "admin123").strip() or "admin123"
# "password" = built-in username/password login (default).
# "access"   = trust upstream identity (Cloudflare Access / reverse proxy).
#              Web admin APIs are open (the proxy is the gate); the /mcp
#              endpoint keeps its own Bearer-token auth (see mcp_server.py).
AUTH_MODE = (os.environ.get("RELAY_AUTH_MODE") or "password").strip().lower()
if AUTH_MODE not in ("password", "access"):
    AUTH_MODE = "password"
# UI login sessions: token -> {user, exp_iso}
_SESSIONS: dict[str, dict[str, str]] = {}
SESSION_TTL_HOURS = int(os.environ.get("RELAY_SESSION_TTL_HOURS") or "168")


def _bearer_token(authorization: str | None, x_device_token: str | None = None) -> str | None:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if x_device_token:
        token = x_device_token.strip()
    return token or None


def _token_ok(got: str, expected: str) -> bool:
    if not got or not expected or len(got) != len(expected):
        return False
    return secrets.compare_digest(got.encode("utf-8"), expected.encode("utf-8"))


def _session_valid(token: str) -> dict[str, str] | None:
    sess = _SESSIONS.get(token)
    if not sess:
        return None
    try:
        exp = datetime.fromisoformat(sess["exp"])
    except (KeyError, ValueError):
        _SESSIONS.pop(token, None)
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) >= exp:
        _SESSIONS.pop(token, None)
        return None
    return sess


def _create_session(username: str) -> dict[str, Any]:
    from datetime import timedelta

    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(hours=max(1, SESSION_TTL_HOURS))
    _SESSIONS[token] = {"user": username, "exp": exp.isoformat()}
    return {"token": token, "user": username, "expires_at": exp.isoformat()}


def require_device(
    authorization: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> sqlite3.Row:
    token = _bearer_token(authorization, x_device_token)
    if not token:
        raise HTTPException(401, "device token required")
    with db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_token=?", (token,)).fetchone()
    if not row:
        raise HTTPException(401, "invalid device token")
    return row


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """Accept UI session token or RELAY_ADMIN_TOKEN (MCP/scripts).

    In AUTH_MODE=access the reverse proxy (Cloudflare Access) is the identity
    gate, so web admin APIs are left open here; the /mcp endpoint enforces its
    own Bearer-token auth regardless of mode.
    """
    if AUTH_MODE == "access":
        return
    got = _bearer_token(authorization)
    if not got:
        raise HTTPException(401, "login required")
    if _session_valid(got):
        return
    if ADMIN_TOKEN and _token_ok(got, ADMIN_TOKEN):
        return
    raise HTTPException(401, "invalid credentials")


# --- Agent API ---


class DetectedAgent(BaseModel):
    id: str
    path: str | None = None
    present: bool = True


class RegisterRequest(BaseModel):
    device_id: str | None = None
    profile: str
    targets: list[str] = Field(default_factory=list)
    hostname: str | None = None
    agent_version: str = "0.1.0"
    detected: list[DetectedAgent] = Field(default_factory=list)


@app.post("/api/v1/devices/register")
def register_device(
    body: RegisterRequest,
    authorization: str | None = Header(default=None),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
) -> dict[str, Any]:
    if body.profile not in PROFILES:
        raise HTTPException(400, f"invalid profile: {body.profile}")
    targets = [t for t in body.targets if t in TARGETS]
    detected = [
        {"id": d.id, "path": d.path, "present": d.present}
        for d in body.detected
        if d.id in TARGETS
    ]
    detected_ids = [d["id"] for d in detected if d.get("present", True)]
    # Union body targets with detected agents so stale client configs cannot drop agents.
    for tid in detected_ids:
        if tid not in targets:
            targets.append(tid)
    device_id = body.device_id or f"{body.profile}-{secrets.token_hex(6)}"
    token = secrets.token_urlsafe(32)
    now = utcnow()
    provided = _bearer_token(authorization, x_device_token)
    with db() as conn:
        existing = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if existing:
            # Never hand out an existing device_token without proving possession.
            if not provided or not _token_ok(provided, existing["device_token"]):
                raise HTTPException(
                    409,
                    "device_id already registered; send Authorization: Bearer <existing device token>",
                )
            # keep agent_config; refresh detection + union targets with previous
            prev_targets = json.loads(existing["targets_json"] or "[]")
            for tid in prev_targets:
                if tid in TARGETS and tid not in targets:
                    targets.append(tid)
            if not targets:
                targets = [t for t in prev_targets if t in TARGETS]
            conn.execute(
                """UPDATE devices SET profile=?, targets_json=?, hostname=?, agent_version=?,
                   detected_json=?, last_seen_at=? WHERE device_id=?""",
                (
                    body.profile,
                    json.dumps(targets),
                    body.hostname,
                    body.agent_version,
                    json.dumps(detected),
                    now,
                    device_id,
                ),
            )
            token = existing["device_token"]
        else:
            # seed agent_config for each target
            agent_cfg = {t: {"enabled": True, "servers": {}} for t in targets}
            conn.execute(
                """INSERT INTO devices(device_id, device_token, profile, targets_json, hostname,
                   agent_version, created_at, agent_config_json, detected_json, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    device_id,
                    token,
                    body.profile,
                    json.dumps(targets),
                    body.hostname,
                    body.agent_version,
                    now,
                    json.dumps(agent_cfg),
                    json.dumps(detected),
                    now,
                ),
            )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("device.register", json.dumps({"device_id": device_id, "targets": targets, "detected": detected}), now),
        )
    return {"device_id": device_id, "device_token": token, "profile": body.profile, "targets": targets}


@app.get("/api/v1/devices/me")
def device_me(device: sqlite3.Row = Depends(require_device)) -> dict[str, Any]:
    return device_dict(device)


@app.get("/api/v1/releases/latest")
def latest_release(
    profile: str | None = Query(None),
    targets: str = Query(""),
    device: sqlite3.Row = Depends(require_device),
) -> dict[str, Any]:
    """Build device-scoped artifact (bindings ∩ device agent_config)."""
    d = device_dict(device)
    if profile and profile != d["profile"]:
        # allow override for debugging but default to device profile
        d["profile"] = profile
    tlist = [t.strip() for t in targets.split(",") if t.strip()]
    if tlist:
        d["targets"] = [t for t in tlist if t in TARGETS]
    artifact = build_artifact_for_device(d)
    etag = secrets.token_hex(8)
    with db() as conn:
        row = conn.execute("SELECT * FROM releases ORDER BY created_at DESC LIMIT 1").fetchone()
        if row:
            prev = json.loads(row["artifact_json"])
            if (
                prev.get("profile") == artifact["profile"]
                and prev.get("targets") == artifact["targets"]
                and prev.get("skills") == artifact["skills"]
                and prev.get("device_id") == d["device_id"]
            ):
                return {
                    "id": row["id"],
                    "etag": row["etag"],
                    "created_at": row["created_at"],
                    "changelog": row["changelog"],
                    "artifact": prev,
                }

        rid = f"rel-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{etag[:4]}"
        artifact["device_id"] = d["device_id"]
        conn.execute(
            "INSERT INTO releases(id, changelog, created_at, etag, artifact_json) VALUES (?,?,?,?,?)",
            (rid, f"device:{d['device_id']}", utcnow(), etag, json.dumps(artifact)),
        )
        conn.execute(
            "UPDATE devices SET last_seen_at=? WHERE device_id=?",
            (utcnow(), d["device_id"]),
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


@app.websocket("/api/v1/devices/ws")
async def device_websocket(websocket: WebSocket, token: str = Query(default="")) -> None:
    """Device long-lived connection for push.apply.

    Auth preference: Authorization Bearer, then first JSON auth message,
    then legacy ?token= (discouraged — may appear in access logs).
    """
    from .hub import hub
    from .push import flush_pending, record_push_ack

    await websocket.accept()
    device_id: str | None = None
    try:
        auth_hdr = websocket.headers.get("authorization") or ""
        if auth_hdr.lower().startswith("bearer "):
            token = auth_hdr[7:].strip()
        if not token:
            first = await websocket.receive_text()
            try:
                msg = json.loads(first)
            except json.JSONDecodeError:
                await websocket.close(code=4400, reason="invalid json")
                return
            if msg.get("type") == "auth":
                token = str(msg.get("token") or "")
            else:
                await websocket.close(code=4401, reason="auth required")
                return
        if not token:
            await websocket.close(code=4401, reason="missing token")
            return
        with db() as conn:
            row = conn.execute("SELECT * FROM devices WHERE device_token=?", (token,)).fetchone()
        if not row:
            await websocket.close(code=4401, reason="invalid token")
            return
        device_id = row["device_id"]
        await hub.connect(device_id, websocket)
        await websocket.send_json({"type": "connected", "device_id": device_id})
        with db() as conn:
            conn.execute(
                "UPDATE devices SET last_seen_at=? WHERE device_id=?",
                (utcnow(), device_id),
            )
            await flush_pending(hub, conn, device_id)

        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid json"})
                continue
            typ = msg.get("type")
            if typ == "ping":
                with db() as conn:
                    conn.execute(
                        "UPDATE devices SET last_seen_at=? WHERE device_id=?",
                        (utcnow(), device_id),
                    )
                await websocket.send_json({"type": "pong"})
            elif typ == "push.ack":
                delivery_id = msg.get("delivery_id")
                if not delivery_id:
                    continue
                with db() as conn:
                    record_push_ack(
                        conn,
                        delivery_id=str(delivery_id),
                        ok=bool(msg.get("ok", True)),
                        detail=msg.get("detail") if isinstance(msg.get("detail"), dict) else {},
                        device_id=device_id,
                    )
                await websocket.send_json({"type": "push.ack.received", "delivery_id": delivery_id})
            else:
                await websocket.send_json({"type": "error", "message": f"unknown type: {typ}"})
    except WebSocketDisconnect:
        pass
    finally:
        if device_id:
            await hub.disconnect(device_id, websocket)


# --- Admin API (requires RELAY_ADMIN_TOKEN / RELAY_MCP_ADMIN_TOKEN) ---


class LogicalIn(BaseModel):
    id: str
    display_name: str | None = None
    transport: str
    default: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


@app.get("/api/v1/logical-servers", dependencies=[Depends(require_admin)])
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


@app.post("/api/v1/logical-servers", dependencies=[Depends(require_admin)])
def upsert_logical(body: LogicalIn) -> dict[str, str]:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO logical_servers(id, display_name, transport, default_json, tags_json) VALUES (?,?,?,?,?)",
            (body.id, body.display_name or body.id, body.transport, json.dumps(body.default), json.dumps(body.tags)),
        )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("logical.upsert", json.dumps({"id": body.id}), utcnow()),
        )
    return {"status": "ok"}


@app.delete("/api/v1/logical-servers/{logical_id}", dependencies=[Depends(require_admin)])
def delete_logical(logical_id: str) -> dict[str, str]:
    with db() as conn:
        conn.execute("DELETE FROM bindings WHERE logical_id=?", (logical_id,))
        conn.execute("DELETE FROM logical_servers WHERE id=?", (logical_id,))
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("logical.delete", json.dumps({"id": logical_id}), utcnow()),
        )
    return {"status": "ok"}


class BindingIn(BaseModel):
    logical_id: str
    profile: str
    target: str
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/v1/bindings", dependencies=[Depends(require_admin)])
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


@app.post("/api/v1/bindings", dependencies=[Depends(require_admin)])
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
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            (
                "binding.upsert",
                json.dumps({"logical_id": body.logical_id, "profile": body.profile, "target": body.target}),
                utcnow(),
            ),
        )
    return {"status": "ok"}


@app.delete("/api/v1/bindings/{binding_id}", dependencies=[Depends(require_admin)])
def delete_binding(binding_id: int) -> dict[str, str]:
    with db() as conn:
        conn.execute("DELETE FROM bindings WHERE id=?", (binding_id,))
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("binding.delete", json.dumps({"id": binding_id}), utcnow()),
        )
    return {"status": "ok"}


@app.get("/api/v1/preview", dependencies=[Depends(require_admin)])
def preview_render(profile: str = Query(...), target: str = Query(...)) -> dict[str, Any]:
    if profile not in PROFILES or target not in TARGETS:
        raise HTTPException(400, "invalid profile/target")
    artifact = build_artifact(profile, [target])
    return {
        "profile": profile,
        "target": target,
        "servers": artifact.get("targets", {}).get(target, {}),
        "skills": artifact.get("skills", []),
        "built_at": artifact.get("built_at"),
    }


@app.get("/api/v1/meta", dependencies=[Depends(require_admin)])
def meta() -> dict[str, Any]:
    return {"targets": list(TARGETS), "profiles": list(PROFILES), "version": "0.1.0"}


@app.post("/api/v1/releases", dependencies=[Depends(require_admin)])
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


@app.get("/api/v1/devices", dependencies=[Depends(require_admin)])
def list_devices() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM devices ORDER BY last_seen_at DESC, created_at DESC").fetchall()
        return [enrich_device(device_dict(r), conn) for r in rows]


@app.delete("/api/v1/devices/{device_id}", dependencies=[Depends(require_admin)])
async def delete_device(device_id: str) -> dict[str, Any]:
    """Remove device and revoke its token. Client must re-init with URL to return."""
    from .hub import hub

    with db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            raise HTTPException(404, "device not found")
        conn.execute("DELETE FROM sync_reports WHERE device_id=?", (device_id,))
        conn.execute("DELETE FROM push_deliveries WHERE device_id=?", (device_id,))
        conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            (
                "device.delete",
                json.dumps({"device_id": device_id, "hostname": row["hostname"], "profile": row["profile"]}),
                utcnow(),
            ),
        )
    await hub.force_disconnect(device_id, code=4001, reason="device deleted")
    return {"status": "deleted", "device_id": device_id}


@app.get("/api/v1/push-deliveries", dependencies=[Depends(require_admin)])
def list_push_deliveries(
    device_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    from .push import list_deliveries

    with db() as conn:
        return list_deliveries(conn, device_id=device_id, limit=limit)


@app.get("/api/v1/devices/{device_id}", dependencies=[Depends(require_admin)])
def get_device(device_id: str) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if not row:
        raise HTTPException(404, "device not found")
    d = device_dict(row)
    # enrichment: effective servers per agent from pinned docs only
    artifact = build_artifact_for_device(d)
    agents_view = []
    for t in d["targets"]:
        ac = (d.get("agent_config") or {}).get(t) or {"enabled": True, "servers": {}}
        effective_map = (artifact.get("targets") or {}).get(t, {}) or {}
        pinned = ac.get("mcp_servers")
        saved_doc = {"mcpServers": pinned if isinstance(pinned, dict) else {}}
        agents_view.append(
            {
                "id": t,
                "enabled": ac.get("enabled", True),
                "servers": ac.get("servers") or {},
                "mcp_servers": pinned if isinstance(pinned, dict) else None,
                "effective_servers": list(effective_map.keys()),
                "mcp_document": saved_doc,
                "detected": next((x for x in (d.get("detected") or []) if x.get("id") == t), None),
            }
        )
    # also show detected-but-not-in-targets
    for det in d.get("detected") or []:
        if det.get("id") in d["targets"]:
            continue
        if det.get("id") not in TARGETS:
            continue
        agents_view.append(
            {
                "id": det["id"],
                "enabled": False,
                "servers": {},
                "mcp_servers": None,
                "effective_servers": [],
                "mcp_document": {"mcpServers": {}},
                "detected": det,
            }
        )
    d["agents"] = agents_view
    d["effective_artifact"] = artifact
    with db() as conn:
        return enrich_device(d, conn)


class AgentConfigPatch(BaseModel):
    """Per-device agent configuration."""

    targets: list[str] | None = None
    agent_config: dict[str, Any] | None = None


def _normalize_agent_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Accept UI/API shapes: flags and/or full mcp document.

    Explicit mcp_document / mcp_servers / mcpServers always replaces the pinned
    document. Omitting all three keeps the previous pin (caller merges).
    """
    cur: dict[str, Any] = {"enabled": True, "servers": {}}
    if "enabled" in entry:
        cur["enabled"] = bool(entry["enabled"])
    if "servers" in entry and isinstance(entry["servers"], dict):
        cur["servers"] = {str(k): bool(v) for k, v in entry["servers"].items()}

    mcp_servers = entry.get("mcp_servers")
    if mcp_servers is None and isinstance(entry.get("mcpServers"), dict):
        mcp_servers = entry["mcpServers"]
    if mcp_servers is None and isinstance(entry.get("mcp_document"), dict):
        doc = entry["mcp_document"]
        if "mcpServers" in doc:
            mcp_servers = doc.get("mcpServers")
        elif "mcp_servers" in doc:
            mcp_servers = doc.get("mcp_servers")
        elif doc and all(isinstance(v, dict) for v in doc.values()):
            # bare servers map sent as mcp_document
            mcp_servers = doc
    if isinstance(mcp_servers, dict):
        cleaned = {str(k): (v if isinstance(v, dict) else {}) for k, v in mcp_servers.items()}
        cur["mcp_servers"] = cleaned
        flags = dict(cur.get("servers") or {})
        for sid in cleaned:
            flags[sid] = True
        cur["servers"] = flags
    elif "mcp_servers" in entry and entry["mcp_servers"] is None:
        # explicit clear of pinned document
        cur.pop("mcp_servers", None)
    return cur


@app.patch("/api/v1/devices/{device_id}/agents", dependencies=[Depends(require_admin)])
async def patch_device_agents(device_id: str, body: AgentConfigPatch) -> dict[str, Any]:
    from .hub import hub
    from .push import enqueue_push

    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            raise HTTPException(404, "device not found")
        d = device_dict(row)
        targets = list(d["targets"])
        cfg = dict(d.get("agent_config") or {})
        if body.targets is not None:
            targets = [t for t in body.targets if t in TARGETS]
        if body.agent_config is not None:
            for agent, entry in body.agent_config.items():
                if agent not in TARGETS:
                    continue
                if not isinstance(entry, dict):
                    raise HTTPException(400, f"agent_config.{agent} must be object")
                prev = dict(cfg.get(agent) or {"enabled": True, "servers": {}})
                provides_doc = any(k in entry for k in ("mcp_servers", "mcpServers", "mcp_document"))
                nxt = _normalize_agent_entry(entry)
                if not provides_doc and "mcp_servers" in prev:
                    nxt["mcp_servers"] = prev["mcp_servers"]
                if "enabled" not in entry:
                    nxt["enabled"] = prev.get("enabled", True)
                if "servers" in entry:
                    servers = dict(prev.get("servers") or {})
                    servers.update(nxt.get("servers") or {})
                    nxt["servers"] = servers
                elif "mcp_servers" not in nxt:
                    nxt["servers"] = prev.get("servers") or {}
                cfg[agent] = nxt
                if nxt.get("enabled", True) and agent not in targets:
                    targets.append(agent)
        conn.execute(
            "UPDATE devices SET targets_json=?, agent_config_json=? WHERE device_id=?",
            (json.dumps(targets), json.dumps(cfg), device_id),
        )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            ("device.agents.patch", json.dumps({"device_id": device_id, "targets": targets, "agent_config": cfg}), utcnow()),
        )
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        assert row is not None
        await enqueue_push(
            hub,
            conn,
            device_id=device_id,
            device_row=row,
            targets=targets,
            trigger="admin_save",
            trigger_detail={"source": "patch_device_agents", "agent_config": body.agent_config},
            build_artifact_for_device=build_artifact_for_device,
        )
    return get_device(device_id)


class BootstrapIn(BaseModel):
    mcp_document: dict[str, Any] | None = None
    mcp_servers: dict[str, Any] | None = None
    mcpServers: dict[str, Any] | None = None


def _extract_mcp_servers(body: BootstrapIn) -> dict[str, Any]:
    if isinstance(body.mcp_servers, dict):
        return body.mcp_servers
    if isinstance(body.mcpServers, dict):
        return body.mcpServers
    if isinstance(body.mcp_document, dict):
        doc = body.mcp_document
        if isinstance(doc.get("mcpServers"), dict):
            return doc["mcpServers"]
        # allow bare servers map as document
        if doc and all(isinstance(v, dict) for v in doc.values()):
            return doc
    raise HTTPException(400, "mcp_document.mcpServers (or mcp_servers) required")


@app.post("/api/v1/devices/me/agents/{target}/bootstrap")
def bootstrap_agent(
    target: str,
    body: BootstrapIn,
    device: sqlite3.Row = Depends(require_device),
) -> dict[str, Any]:
    """Upload local mcpServers only when the agent still has no pinned config.

    Uses BEGIN IMMEDIATE so a concurrent admin save cannot be overwritten.
    """
    if target not in TARGETS:
        raise HTTPException(400, f"invalid target: {target}")
    servers = _extract_mcp_servers(body)
    cleaned = {str(k): (v if isinstance(v, dict) else {}) for k, v in servers.items()}
    device_id = device["device_id"]
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            raise HTTPException(404, "device not found")
        d = device_dict(row)
        cfg = dict(d.get("agent_config") or {})
        prev = dict(cfg.get(target) or {})
        # Any pinned document (including empty {}) means admin/client already decided —
        # never let a concurrent bootstrap overwrite a just-saved config.
        existing = prev.get("mcp_servers")
        if "mcp_servers" in prev and isinstance(existing, dict):
            return {
                "status": "skipped",
                "reason": "already_configured",
                "device_id": device_id,
                "target": target,
                "server_count": len(existing),
            }
        entry = {
            "enabled": True,
            "servers": {sid: True for sid in cleaned},
            "mcp_servers": cleaned,
        }
        cfg[target] = entry
        targets = list(d["targets"])
        if target not in targets:
            targets.append(target)
        conn.execute(
            "UPDATE devices SET targets_json=?, agent_config_json=?, last_seen_at=? WHERE device_id=?",
            (json.dumps(targets), json.dumps(cfg), utcnow(), device_id),
        )
        conn.execute(
            "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
            (
                "device.agents.bootstrap",
                json.dumps({"device_id": device_id, "target": target, "server_count": len(cleaned)}),
                utcnow(),
            ),
        )
    return {
        "status": "ok",
        "device_id": device_id,
        "target": target,
        "server_count": len(cleaned),
        "servers": list(cleaned.keys()),
    }


class ScriptBody(BaseModel):
    script: str
    format: str | None = None  # yaml | dsl | auto
    dry_run: bool = True
    device_ids: list[str] | None = None  # optional filter


@app.post("/api/v1/scripts/parse", dependencies=[Depends(require_admin)])
def scripts_parse(body: ScriptBody) -> dict[str, Any]:
    from .script_parser import parse_script

    script, errors = parse_script(body.script, body.format)
    if errors:
        return {
            "ok": False,
            "errors": [{"line": e.line, "message": e.message} for e in errors],
        }
    assert script is not None
    return {
        "ok": True,
        "version": script.version,
        "source": script.source,
        "ops_count": len(script.ops),
        "ops": [
            {
                "match": {
                    "profile": op.match.profile,
                    "device_id": op.match.device_id,
                    "hostname_contains": op.match.hostname_contains,
                },
                "set_agents": op.set_agents,
                "agents": {
                    k: {
                        "enabled": v.enabled,
                        "enable": v.enable,
                        "disable": v.disable,
                        "enable_all": v.enable_all,
                        "disable_all": v.disable_all,
                    }
                    for k, v in op.agents.items()
                },
            }
            for op in script.ops
        ],
    }


@app.post("/api/v1/scripts/apply", dependencies=[Depends(require_admin)])
async def scripts_apply(body: ScriptBody) -> dict[str, Any]:
    from .hub import hub
    from .push import enqueue_push
    from .script_parser import apply_script_to_device_config, parse_script

    script, errors = parse_script(body.script, body.format)
    if errors:
        raise HTTPException(400, {"errors": [{"line": e.line, "message": e.message} for e in errors]})
    assert script is not None
    known = known_logical_ids()
    with db() as conn:
        rows = conn.execute("SELECT * FROM devices").fetchall()
    results = []
    applied = 0
    for row in rows:
        d = device_dict(row)
        if body.device_ids and d["device_id"] not in body.device_ids:
            continue
        new_cfg, new_targets, changed = apply_script_to_device_config(
            d, d.get("agent_config") or {}, script, known
        )
        if not changed:
            continue
        entry = {
            "device_id": d["device_id"],
            "hostname": d.get("hostname"),
            "profile": d["profile"],
            "before": {"targets": d["targets"], "agent_config": d.get("agent_config") or {}},
            "after": {"targets": new_targets, "agent_config": new_cfg},
        }
        results.append(entry)
        if not body.dry_run:
            device_id = d["device_id"]
            with db() as conn:
                conn.execute(
                    "UPDATE devices SET targets_json=?, agent_config_json=? WHERE device_id=?",
                    (json.dumps(new_targets), json.dumps(new_cfg), device_id),
                )
                fresh = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
                if fresh is not None:
                    await enqueue_push(
                        hub,
                        conn,
                        device_id=device_id,
                        device_row=fresh,
                        targets=new_targets,
                        trigger="script_apply",
                        trigger_detail={"script_format": body.format},
                        build_artifact_for_device=build_artifact_for_device,
                    )
            applied += 1
    if not body.dry_run and results:
        with db() as conn:
            conn.execute(
                "INSERT INTO audit_log(action, detail_json, created_at) VALUES (?,?,?)",
                (
                    "script.apply",
                    json.dumps({"matched": len(results), "dry_run": False, "devices": [r["device_id"] for r in results]}),
                    utcnow(),
                ),
            )
    return {
        "ok": True,
        "dry_run": body.dry_run,
        "matched": len(results),
        "applied": applied if not body.dry_run else 0,
        "results": results,
    }


@app.get("/api/v1/scripts/examples", dependencies=[Depends(require_admin)])
def scripts_examples() -> dict[str, str]:
    return {
        "yaml": """version: 1
ops:
  - match:
      profile: windows-desktop
    agents:
      cursor:
        enable: [trek, nowledge-mem, drawio]
        disable: [jeb]
      pi:
        enabled: true
        enable: [trek]
  - match:
      profile: linux-server
    agents:
      hermes:
        enable_all: true
""",
        "dsl": """# batch enable MCP servers on all windows-desktop devices
enable profile:windows-desktop agent:cursor trek nowledge-mem drawio
disable profile:windows-desktop agent:cursor jeb
enable_all profile:linux-server agent:hermes
set profile:windows-desktop agents=cursor,pi,codex,claude-code
""",
    }


@app.get("/api/v1/releases/{release_id}/diff/{prev_id}", dependencies=[Depends(require_admin)])
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


@app.get("/api/v1/skill-packs", dependencies=[Depends(require_admin)])
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


@app.get("/api/v1/audit", dependencies=[Depends(require_admin)])
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


from .mcp_server import get_mcp_lifespan, mount_mcp

mount_mcp(app)