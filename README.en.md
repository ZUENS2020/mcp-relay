# MCP Relay

[中文](./README.md)

Central **MCP / Skill** configuration for multiple machines and agents: define once → push per device × agent → clients sync to local config files.

**Supported agents:** `cursor` · `hermes` · `pi` · `codex` · `claude-code`

| | |
|---|---|
| npm | [`@zuens2020/mcp-relay`](https://www.npmjs.com/package/@zuens2020/mcp-relay) |
| Repo | [ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay) |
| Console | https://example.com (LAN: `http://127.0.0.1:8740`) |

## Quick start (client)

```bash
npm i -g @zuens2020/mcp-relay

mcp-relay init --url https://example.com
# LAN: mcp-relay init --url http://127.0.0.1:8740

mcp-relay sync
```

### What `sync` does by default (live)

1. **Backup** local MCP configs under `~/.mcp-relay/backups/<timestamp>/`
2. If the server has **no** config for an agent, **upload** the local mcp.json (bootstrap)
3. **Apply** the server-side document back to the machine

Debug options:

```bash
mcp-relay sync --dry-run
mcp-relay sync --sandbox
mcp-relay backup list
mcp-relay backup restore --latest
```

## Common commands

```bash
mcp-relay doctor
mcp-relay config get
mcp-relay config set url https://example.com
mcp-relay register
mcp-relay connect          # WebSocket keep-alive (save-and-push)
mcp-relay watch            # connect + periodic sync fallback
  mcp-relay update [--check]   # check/upgrade npm package (watch/connect auto-update every 6h)
  mcp-relay version
```

Config: `mcp-relay config set auto_update true|false` (default on).

## Architecture

| Component | Stack | Role |
|-----------|-------|------|
| `services/relay-api` | FastAPI + SQLite | Registry, bootstrap, admin UI |
| `packages/mcp-relay` | npm CLI | Install entry + server URL |
| `packages/mcp-relay-*` | optional platform pkgs | Prebuilt Go `relay-agent` |
| `agent/` | Go | Detect, backup, five adapters |
| `config-repo/` | JSON | Logical servers + bindings |

```
Device ──connect/ws──▶ Relay API ──push.apply──▶ Agent writes local mcp.json
        sync fallback ▲        │
Admin: Config (device · agent · mcp.json) · Scripts · Overview · Audit
                        ▲
Cursor etc. ── MCP /mcp ── read/write devices, trigger push
```

### Real-time push

- Run `mcp-relay connect` (or `watch`, which includes WS) to show **green online** in the admin UI
- Saving agent config in the console **pushes immediately**; offline devices queue until reconnect
- Delivery status via `GET /api/v1/push-deliveries` or MCP `relay_list_push_deliveries` (`queued → sent → acked/failed`)

### Admin Config page

- Editor shows only the agent's **saved** `mcpServers` document (no Profile binding defaults)
- **CodeMirror 6**: highlighting, auto-indent, JSON lint; **Format** or `Ctrl/⌘+Shift+F`
- **Restore last save**: discard unsaved edits (does not clear back to Profile defaults)
- **Delete device**: revokes token and closes WS; client must `mcp-relay init --url …` again

### Admin login

The console uses **username/password** (no admin-token prompt):

| | Default | Override |
|---|---|---|
| Username | `admin` | `RELAY_ADMIN_USER` |
| Password | `admin123` | `RELAY_ADMIN_PASSWORD` |

Login issues a session stored in tab `sessionStorage`; use **Log out** in the sidebar. Change the default password in production.

Synced artifacts use each agent's **saved mcp.json** only (Profile bindings are not merged).

### Relay MCP admin API

Optionally set `RELAY_ADMIN_TOKEN` / `RELAY_MCP_ADMIN_TOKEN` for MCP tools and scripts (Bearer; independent of UI login):

```json
{
  "mcpServers": {
    "mcp-relay": {
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer <RELAY_MCP_ADMIN_TOKEN>"
      }
    }
  }
}
```

Tools include `relay_list_devices`, `relay_get_device`, `relay_delete_device`, `relay_patch_device_agents` (save + push), `relay_list_push_deliveries`, `relay_apply_script`, etc.


## Deploy (server)

```bash
bash scripts/deploy-nec.sh
```

Suggested `.env` (or host env) next to `docker-compose.yml`:

```bash
RELAY_ADMIN_USER=admin
RELAY_ADMIN_PASSWORD=change-me
# Optional: MCP / script Bearer (separate from UI login)
RELAY_ADMIN_TOKEN=
```

- Health: `GET /health`
- Public tunnel notes: [`docs/cloudflare-tunnel.md`](./docs/cloudflare-tunnel.md)
- npm publish: [`docs/npm-publish.md`](./docs/npm-publish.md) (tag `cli-v*`, CLI **0.2.4**)

## Local development

```bash
cd services/relay-api
pip install -r requirements.txt
pip install -r requirements-mcp.txt   # optional: /mcp admin tools
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740

bash scripts/build-agent-binaries.sh
```

Admin UI follows the **Suzuka Design System**. Config page: resizable columns (device · agent · mcp.json).

## License

[MIT](./LICENSE)
