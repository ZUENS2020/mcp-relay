# @zuens2020/mcp-relay

MCP Relay 客户端：一键安装，CLI 配置服务端，同步本机 Agent 的 MCP 配置。

## 安装

```bash
npm i -g @zuens2020/mcp-relay
```

国内网络建议：

```bash
npm config set registry https://registry.npmmirror.com
npm i -g @zuens2020/mcp-relay
```

## 快速开始

```bash
mcp-relay init --url https://example.com
# 或局域网
mcp-relay init --url http://127.0.0.1:8740

mcp-relay sync
```

默认同步（live）：

1. 备份本地 MCP 配置到 `~/.mcp-relay/backups/`
2. 若服务端该 Agent 尚无配置，上传本地 mcp.json
3. 按服务端配置写回本机

## 常用命令

```bash
mcp-relay config set url http://127.0.0.1:8740
mcp-relay config get
mcp-relay doctor
mcp-relay register
mcp-relay sync
mcp-relay sync --dry-run
mcp-relay sync --sandbox
mcp-relay backup list
mcp-relay backup restore --latest
mcp-relay version
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `RELAY_URL` | 服务端地址（也可写进 config） |
| `RELAY_ROOT` | 默认 `~/.mcp-relay` |
| `RELAY_MODE` | `live`（默认）/ `sandbox` / `dry-run` |
| `MCP_RELAY_BIN` | 强制指定 Go 二进制路径 |

## 平台包

主包通过 `optionalDependencies` 安装对应平台二进制：

- `@zuens2020/mcp-relay-win32-x64`
- `@zuens2020/mcp-relay-darwin-x64`
- `@zuens2020/mcp-relay-darwin-arm64`
- `@zuens2020/mcp-relay-linux-x64`
