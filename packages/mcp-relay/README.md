# @zuens2020/mcp-relay

[English](./README.en.md)

MCP Relay 客户端：一键安装，配置服务端，备份并同步本机 Agent 的 MCP。

## 安装

```bash
npm i -g @zuens2020/mcp-relay
```

若国内镜像尚未同步到最新版本：

```bash
npm i -g @zuens2020/mcp-relay --registry https://registry.npmjs.org/
```

## 快速开始

```bash
mcp-relay init --url https://example.com
mcp-relay sync
```

局域网：

```bash
mcp-relay init --url http://127.0.0.1:8740
mcp-relay sync
```

### live 同步顺序

1. 备份到 `~/.mcp-relay/backups/`
2. 服务端为空则 bootstrap 上传本地配置
3. 按下发结果写回本机

## 命令

```bash
mcp-relay doctor
mcp-relay config set url <URL>
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

配置：`mcp-relay config set auto_update true|false`（默认开；watch/connect 约每 6h 自动升级）。

设备若在管理台被删除，客户端会清空本地注册，需重新 `mcp-relay init --url …`。

## 环境变量

| 变量 | 说明 |
|------|------|
| `RELAY_URL` | 服务端地址 |
| `RELAY_ROOT` | 默认 `~/.mcp-relay` |
| `RELAY_MODE` | `live`（默认）/ `sandbox` / `dry-run` |
| `MCP_RELAY_BIN` | 强制指定 `relay-agent` 路径 |

## 平台包

通过 `optionalDependencies` 安装：

- `@zuens2020/mcp-relay-win32-x64`
- `@zuens2020/mcp-relay-darwin-x64`
- `@zuens2020/mcp-relay-darwin-arm64`
- `@zuens2020/mcp-relay-linux-x64`

安装后 `postinstall` 会确保 Unix 二进制可执行。

## 许可

MIT · 仓库 [ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay)
