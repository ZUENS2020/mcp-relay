# MCP Relay

多端 MCP / Skill 配置中心：中心定义 → 按设备 × Agent 下发 → 客户端同步写入。

**Targets (MVP):** `cursor` | `hermes` | `pi` | `codex` | `claude-code`

仓库：[ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay) · 部署目标：NEC `127.0.0.1`

## 客户端（推荐）

```bash
npm i -g @zuens2020/mcp-relay
# 国内可先：npm config set registry https://registry.npmmirror.com

mcp-relay init --url http://127.0.0.1:8740
mcp-relay sync
```

默认同步（**live**）：先备份本地 MCP → 服务端无配置则上传本地 → 再按下发写回。  
调试可用 `mcp-relay sync --dry-run` 或 `--sandbox`。

详情见 `packages/mcp-relay/README.md`。发布 tag：`cli-v0.2.0`。

## 组件

| 组件 | 技术 | 说明 |
|------|------|------|
| `services/relay-api` | FastAPI + SQLite | 设备注册、bootstrap、管理 UI |
| `packages/mcp-relay` | npm CLI | 一键安装 + 配置服务端 |
| `agent/` | Go `relay-agent` | 探测、备份、bootstrap、五套 adapter |
| `config-repo/` | JSON | logical servers + bindings 样例 |
| `skills-repo/` | SKILL.md packs | 技能包分发 |

## 同步模式

| 模式 | 用法 |
|------|------|
| live（默认） | `mcp-relay sync` → 备份后写真实 home（`~/.mcp-relay`） |
| dry-run | `mcp-relay sync --dry-run` → 只出 diff |
| sandbox | `mcp-relay sync --sandbox` → 写到沙箱 home |

## 本地开发

```bash
# API
cd services/relay-api
pip install -r requirements.txt
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740

# Agent (Go) → 平台 npm 包
bash scripts/build-agent-binaries.sh
cd packages/mcp-relay && npm link
# Windows 也可：go build -o ../packages/mcp-relay-win32-x64/bin/relay-agent.exe ./cmd/relay-agent
```

## UI

管理台按 **Suzuka Design System**（`ZUENS2020/Design-Systems`）落地。默认页「配置」：设备 → Agent → 整份 mcp.json。

打开：http://127.0.0.1:8740

```bash
bash scripts/deploy-nec.sh
```

- LAN：`http://127.0.0.1:8740`
- 公网：`https://example.com`（见 `docs/cloudflare-tunnel.md`）

## 布局

```
mcp-relay/
  agent/                 # Go relay-agent
  services/relay-api/    # FastAPI
  config-repo/           # 种子配置
  skills-repo/           # 技能包
  docs/DESIGN.md
  docker-compose.yml
  scripts/deploy-nec.sh
```
