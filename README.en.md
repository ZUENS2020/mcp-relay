# MCP Relay

[中文](./README.md)

A central **MCP config** service for multiple machines and agents: edit mcp.json in the admin UI → sync to each device.

**Supported agents:** `cursor` · `hermes` · `pi` · `codex` · `claude-code`

---

## 1. Run the server

Docker required. From the repo root:

```bash
cp .env.example .env   # optional
docker compose up -d --build
```

Listens on `http://127.0.0.1:8740` by default. Health: `GET /health`.

### Admin login

Open the server URL in a browser:

| | Default | Env override |
|---|---|---|
| Username | `admin` | `RELAY_ADMIN_USER` |
| Password | `admin123` | `RELAY_ADMIN_PASSWORD` |

Change the default password in production. Use **Log out** in the sidebar when done.

Optional: set `RELAY_ADMIN_TOKEN` (or `RELAY_MCP_ADMIN_TOKEN`) for scripts / MCP tools via `Authorization: Bearer …` (independent of UI login).

### Local API without Docker

```bash
cd services/relay-api
pip install -r requirements.txt
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740
```

---

## 2. Install the client

```bash
npm i -g @zuens2020/mcp-relay
```

Replace `<RELAY_URL>` with your server (e.g. `http://127.0.0.1:8740`):

```bash
mcp-relay init --url <RELAY_URL>
mcp-relay sync
```

### What `sync` does

1. **Backup** local MCP configs under `~/.mcp-relay/backups/<timestamp>/`
2. If the server has **no** config for an agent, **upload** local mcp.json (bootstrap)
3. **Apply** the saved server document back to disk

Debug:

```bash
mcp-relay sync --dry-run
mcp-relay sync --sandbox
mcp-relay backup list
mcp-relay backup restore --latest
```

---

## 3. Common commands

```bash
mcp-relay doctor
mcp-relay config get
mcp-relay config set url <RELAY_URL>
mcp-relay register
mcp-relay sync
mcp-relay connect             # WebSocket (push on admin save)
mcp-relay watch               # connect + periodic sync fallback
mcp-relay update [--check]
mcp-relay version
```

Prefer `watch` or `connect` day-to-day so the console shows online and saves push immediately.

If a device is deleted in the admin UI, re-run `mcp-relay init --url …`.

### Client environment

| Variable | Meaning |
|----------|---------|
| `RELAY_URL` | Relay base URL |
| `RELAY_ROOT` | Default `~/.mcp-relay` |
| `RELAY_MODE` | `live` (default) / `sandbox` / `dry-run` |

---

## 4. Using the admin UI

1. **Config**: pick device → agent → edit full `mcp.json`
2. The editor shows only the agent's **saved** document; save to publish
3. **Format** or `Ctrl/⌘+Shift+F`; **Restore last save** discards unsaved edits
4. **Scripts** for bulk enable/disable-style ops
5. **Overview / Audit** for devices and history

Artifacts use each agent's saved `mcpServers` only.

### Real-time push

- Client must run `connect` / `watch`
- Admin save pushes immediately; offline devices queue until reconnect
- Status: `GET /api/v1/push-deliveries` (`queued → sent → acked/failed`)

---

## 5. Optional: manage Relay via MCP

```json
{
  "mcpServers": {
    "mcp-relay": {
      "url": "<RELAY_URL>/mcp",
      "headers": {
        "Authorization": "Bearer <RELAY_ADMIN_TOKEN>"
      }
    }
  }
}
```

Requires `RELAY_ADMIN_TOKEN` / `RELAY_MCP_ADMIN_TOKEN` on the server.

Tools include `relay_list_devices`, `relay_get_device`, `relay_delete_device`, `relay_patch_device_agents`, `relay_list_push_deliveries`, `relay_apply_script`, etc.

---

## License

[MIT](./LICENSE)
