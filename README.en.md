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
Admin UI: online status | push history | agent config
                        ▲
Cursor etc. ── MCP /mcp ── read/write devices, trigger push
```

### Real-time push

- Run `mcp-relay connect` (or `watch`, which includes WS) to show **green online** in the admin UI
- Saving agent config in the console **pushes immediately**; offline devices queue until reconnect
- Sidebar **Push history** shows `queued → sent → acked/failed`

### Relay MCP admin API

Set `RELAY_MCP_ADMIN_TOKEN` on the server, then add Streamable HTTP MCP in Cursor:

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

Tools include `relay_list_devices`, `relay_get_device`, `relay_patch_device_agents` (save + push), `relay_list_push_deliveries`, `relay_apply_script`, etc.


```bash
bash scripts/deploy-nec.sh
```

- Health: `GET /health`
- Public tunnel notes: [`docs/cloudflare-tunnel.md`](./docs/cloudflare-tunnel.md)
- npm publish: [`docs/npm-publish.md`](./docs/npm-publish.md) (tag `cli-v*`)

## Local development

```bash
cd services/relay-api
pip install -r requirements.txt
pip install -r requirements-mcp.txt   # optional: /mcp admin tools
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740

bash scripts/build-agent-binaries.sh
```

Admin UI follows the **Suzuka Design System**. The Config page uses resizable columns (device · agent · mcp.json).

## License

[MIT](./LICENSE)
