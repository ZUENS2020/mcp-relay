# @zuens2020/mcp-relay

[中文](./README.md)

MCP Relay client: install once, point at your relay server, backup and sync local agent MCP configs.

## Install

```bash
npm i -g @zuens2020/mcp-relay
```

## Quick start

```bash
mcp-relay init --url https://example.com
mcp-relay sync
```

### What live sync does

1. Backup under `~/.mcp-relay/backups/`
2. Bootstrap-upload local config when the server has none
3. Apply the server document to disk

## Commands

```bash
mcp-relay doctor
mcp-relay config set url <URL>
mcp-relay sync
mcp-relay sync --dry-run
mcp-relay backup list
mcp-relay backup restore --latest
mcp-relay version
```

## Environment

| Variable | Meaning |
|----------|---------|
| `RELAY_URL` | Relay base URL |
| `RELAY_ROOT` | Default `~/.mcp-relay` |
| `RELAY_MODE` | `live` (default) / `sandbox` / `dry-run` |
| `MCP_RELAY_BIN` | Override path to `relay-agent` |

## Platform packages

Optional dependencies:

- `@zuens2020/mcp-relay-win32-x64`
- `@zuens2020/mcp-relay-darwin-x64`
- `@zuens2020/mcp-relay-darwin-arm64`
- `@zuens2020/mcp-relay-linux-x64`

`postinstall` ensures the Unix binary is executable.

## License

MIT · [ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay)
