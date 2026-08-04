# @zuens2020/mcp-relay

[English](./README.en.md)

MCP Relay 客户端：安装后指向你的服务端，备份并同步本机各 Agent 的 MCP 配置。

完整说明见仓库根目录 [README.md](../../README.md)。

## 安装

```bash
npm i -g @zuens2020/mcp-relay
```

## 快速开始

```bash
mcp-relay init --url <RELAY_URL>   # 例如 http://127.0.0.1:8740
mcp-relay sync
mcp-relay watch                    # 推荐：在线 + 定时兜底
```

### 同步顺序

1. 备份到 `~/.mcp-relay/backups/`
2. 服务端为空则上传本地配置（bootstrap）
3. 按下发结果写回本机

## 命令

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

设备在管理台被删除后，需重新 `mcp-relay init --url …`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `RELAY_URL` | 服务端地址 |
| `RELAY_ROOT` | 默认 `~/.mcp-relay` |
| `RELAY_MODE` | `live`（默认）/ `sandbox` / `dry-run` |
| `MCP_RELAY_BIN` | 强制指定 `relay-agent` 路径 |

## 许可

MIT
