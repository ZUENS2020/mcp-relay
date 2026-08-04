# MCP Relay

[English](./README.en.md)

多设备、多 Agent 的 **MCP 配置中心**：在管理台编辑 mcp.json → 下发到各设备本地。

**支持的 Agent：** `cursor` · `hermes` · `pi` · `codex` · `claude-code`

---

## 1. 启动服务端

需要 Docker。在仓库根目录：

```bash
# 可选：复制并修改环境变量
cp .env.example .env

docker compose up -d --build
```

默认监听 `http://127.0.0.1:8740`。健康检查：`GET /health`。

### 管理台登录

浏览器打开服务地址，使用账密登录：

| | 默认 | 环境变量 |
|---|---|---|
| 用户名 | `admin` | `RELAY_ADMIN_USER` |
| 密码 | `admin123` | `RELAY_ADMIN_PASSWORD` |

生产环境请修改默认密码。侧栏可「退出登录」。

可选：设置 `RELAY_ADMIN_TOKEN`（或 `RELAY_MCP_ADMIN_TOKEN`），供脚本 / MCP 工具用 `Authorization: Bearer …` 调用管理 API（与 UI 登录无关）。

### 本地开发（不用 Docker）

```bash
cd services/relay-api
pip install -r requirements.txt
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740
```

---

## 2. 安装客户端

```bash
npm i -g @zuens2020/mcp-relay
```

将 `<RELAY_URL>` 换成你的服务端地址，例如 `http://127.0.0.1:8740`：

```bash
mcp-relay init --url <RELAY_URL>
mcp-relay sync
```

### 同步会做什么

1. **备份**本地 MCP 到 `~/.mcp-relay/backups/<时间戳>/`
2. 若服务端该 Agent **尚无配置**，把本地 mcp.json **上传（bootstrap）**
3. 按服务端已保存配置 **写回**本机

调试：

```bash
mcp-relay sync --dry-run      # 只看 diff，不写盘
mcp-relay sync --sandbox      # 写到沙箱目录
mcp-relay backup list
mcp-relay backup restore --latest
```

---

## 3. 常用命令

```bash
mcp-relay doctor
mcp-relay config get
mcp-relay config set url <RELAY_URL>
mcp-relay register
mcp-relay sync
mcp-relay connect             # WebSocket 长连接（管理台保存即推送）
mcp-relay watch               # connect + 定时 sync 兜底
mcp-relay update [--check]
mcp-relay version
```

建议日常跑 `mcp-relay watch` 或 `connect`，管理台才会显示在线，且保存后能即时推送。

设备若在管理台被删除，本地注册会失效，需重新 `mcp-relay init --url …`。

### 客户端环境变量

| 变量 | 说明 |
|------|------|
| `RELAY_URL` | 服务端地址 |
| `RELAY_ROOT` | 默认 `~/.mcp-relay` |
| `RELAY_MODE` | `live`（默认）/ `sandbox` / `dry-run` |

---

## 4. 管理台怎么用

1. 登录后进入 **配置**：左选设备 → 中选 Agent → 右编辑完整 `mcp.json`
2. 编辑器只显示该 Agent **已保存**的内容；保存后才会下发
3. **格式化** 或 `Ctrl/⌘+Shift+F`；**恢复上次保存** 可撤销未提交编辑
4. **批量脚本** 可对多台设备批量改开关类配置
5. **总览 / 审计** 查看设备与操作记录

下发内容以各 Agent 已保存的 `mcpServers` 为准。

### 实时推送

- 客户端需运行 `connect` / `watch`
- 管理台保存后自动推送；离线设备会排队，上线后补发
- 状态：`GET /api/v1/push-deliveries`（`queued → sent → acked/failed`）

---

## 5. 用 MCP 管理 Relay（可选）

在 Cursor 等客户端添加（把 URL 与令牌换成你的）：

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

需服务端已设置 `RELAY_ADMIN_TOKEN` / `RELAY_MCP_ADMIN_TOKEN`。

常用工具：`relay_list_devices`、`relay_get_device`、`relay_delete_device`、`relay_patch_device_agents`、`relay_list_push_deliveries`、`relay_apply_script` 等。

---

## 许可

[MIT](./LICENSE)
