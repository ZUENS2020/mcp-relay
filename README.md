# MCP Relay

[English](./README.en.md)

多端 **MCP / Skill 配置中心**：中心定义一次 → 按设备 × Agent 下发 → 客户端同步写入本地。

**支持的 Agent：** `cursor` · `hermes` · `pi` · `codex` · `claude-code`

| | |
|---|---|
| npm | [`@zuens2020/mcp-relay`](https://www.npmjs.com/package/@zuens2020/mcp-relay) |
| 仓库 | [ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay) |
| 控制台 | https://example.com （局域网 `http://127.0.0.1:8740`） |

## 快速开始（客户端）

```bash
npm i -g @zuens2020/mcp-relay
# 国内镜像若尚未同步，请用官方源：
# npm i -g @zuens2020/mcp-relay --registry https://registry.npmjs.org/

mcp-relay init --url https://example.com
# 或局域网：mcp-relay init --url http://127.0.0.1:8740

mcp-relay sync
```

### 默认同步会做什么（live）

1. **备份**本地 MCP 配置到 `~/.mcp-relay/backups/<时间戳>/`
2. 若服务端该 Agent **尚无配置**，将本地 mcp.json **上传（bootstrap）**
3. 按服务端配置 **写回**本机

调试：

```bash
mcp-relay sync --dry-run     # 只看 diff，不写盘
mcp-relay sync --sandbox     # 写到沙箱 home
mcp-relay backup list
mcp-relay backup restore --latest
```

## 常用命令

```bash
mcp-relay doctor
mcp-relay config get
mcp-relay config set url https://example.com
mcp-relay register
mcp-relay connect          # WebSocket 长连接（保存即推）
mcp-relay watch            # connect + 定时 sync 兜底
  mcp-relay update [--check]   # 检查/升级 npm 包（watch/connect 默认每 6h 自动升级）
  mcp-relay version
```

配置项：`mcp-relay config set auto_update true|false`（默认开启）。

## 架构

| 组件 | 技术 | 说明 |
|------|------|------|
| `services/relay-api` | FastAPI + SQLite | 注册、bootstrap、管理台 |
| `packages/mcp-relay` | npm CLI | 安装入口 + 配置服务端 |
| `packages/mcp-relay-*` | 平台 optional 包 | 预编译 Go `relay-agent` |
| `agent/` | Go | 探测、备份、五套 adapter |
| `config-repo/` | JSON | logical servers + bindings |

```
设备 ──connect/ws──▶ Relay API ──push.apply──▶ Agent 写本地 mcp.json
       sync 兜底 ▲         │
管理台：设备在线状态 | 推送记录 | Agent 配置
                 ▲
Cursor 等 ── MCP /mcp ── 读写设备配置、触发推送
```

### 实时推送

- 设备运行 `mcp-relay connect`（或 `watch`，内含 WS）后，管理台显示**绿点在线**
- 在管理台保存 Agent 配置会**自动推送**；离线设备排队，上线后补发
- 侧栏「**推送记录**」可查看 `queued → sent → acked/failed` 状态

### Relay MCP 管理接口

服务端设置 `RELAY_MCP_ADMIN_TOKEN` 后，在 Cursor 等客户端添加 Streamable HTTP MCP：

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

可用工具：`relay_list_devices`、`relay_get_device`、`relay_patch_device_agents`（保存并推送）、`relay_list_push_deliveries`、`relay_apply_script` 等。


## 部署（服务端）

```bash
# 需要 Docker；默认写到 NEC ~/mcp-relay
bash scripts/deploy-nec.sh
```

- 健康检查：`GET /health`
- 公网隧道：见 [`docs/cloudflare-tunnel.md`](./docs/cloudflare-tunnel.md)（NPM 反代 `example.com` → `:8740`）
- npm 发布：见 [`docs/npm-publish.md`](./docs/npm-publish.md)（tag `cli-v*`）

## 本地开发

```bash
# API
cd services/relay-api
pip install -r requirements.txt
pip install -r requirements-mcp.txt   # optional: /mcp admin tools
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740

# Agent 二进制 → 平台包
bash scripts/build-agent-binaries.sh
```

管理台 UI：**Suzuka Design System**；默认页「配置」支持拖拽调节列宽。

## 许可

[MIT](./LICENSE)
