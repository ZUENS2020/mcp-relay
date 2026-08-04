# @zuens2020/mcp-relay

[中文](./README.md)

MCP Relay client: point at your relay server, backup and sync local agent MCP configs.

See the repo root [README.en.md](../../README.en.md) for the full guide.

## Install

```bash
npm i -g @zuens2020/mcp-relay
```

## Quick start

```bash
mcp-relay init --url <RELAY_URL>   # e.g. http://127.0.0.1:8740
mcp-relay sync
mcp-relay watch                    # recommended
```

### Live sync

1. Backup under `~/.mcp-relay/backups/`
2. Bootstrap-upload when the server has no config
3. Apply the server document to disk

## Commands

```bash
mcp-relay doctor
mcp-relay config set url <RELAY_URL>
mcp-relay config get
mcp-relay register
mcp-relay sync
mcp-relay sync --dry-run
mcp-relay sync --sandbox
mcp-relay connect
mcp-relay watch
mcp-relay update [--check]
mcp-relay backup list
mcp-relay backup restore --latest
mcp-relay version
```

If the device was deleted in the admin UI, run `mcp-relay init --url …` again.

## Environment

| Variable | Meaning |
|----------|---------|
| `RELAY_URL` | Relay base URL |
| `RELAY_ROOT` | Default `~/.mcp-relay` |
| `RELAY_MODE` | `live` (default) / `sandbox` / `dry-run` |
| `MCP_RELAY_BIN` | Override path to `relay-agent` |

## License

MIT
