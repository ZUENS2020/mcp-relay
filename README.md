# MCP Relay

多端 MCP / Skill 配置中心：中心定义 → 按 profile×target 渲染 → agent 拉取写入。

**Targets (MVP):** `cursor` | `hermes` | `pi` | `codex` | `claude-code`

仓库：[ZUENS2020/mcp-relay](https://github.com/ZUENS2020/mcp-relay) · 部署目标：NEC `127.0.0.1`

## 组件

| 组件 | 技术 | 说明 |
|------|------|------|
| `services/relay-api` | FastAPI + SQLite | 设备注册、release、管理 UI |
| `agent/` | **Go** `relay-agent` | 自动探测 + sandbox/dry-run/live + 五 adapter |
| `config-repo/` | JSON | logical servers + bindings 样例 |
| `skills-repo/` | SKILL.md packs | 技能包分发 |

## 安全：测试模式（默认不写真实配置）

| 模式 | 用法 |
|------|------|
| sandbox（默认） | `relay-agent sync` → `~/.relay/sandbox/home/` |
| dry-run | `relay-agent sync --dry-run` → 只出 diff |
| live | `relay-agent sync --live` **且** `allow_live_writes: true` |

## 本地开发

```bash
# API
cd services/relay-api
pip install -r requirements.txt
export RELAY_DATA=../../data RELAY_CONFIG_REPO=../../config-repo SKILLS_ROOT=../../skills-repo
uvicorn app.main:app --host 127.0.0.1 --port 8740

# Agent (Go)
cd agent
go test ./...
go build -buildvcs=false -o relay-agent.exe ./cmd/relay-agent
./relay-agent.exe doctor
./relay-agent.exe init-sandbox
./relay-agent.exe register --relay-url http://127.0.0.1:8740
./relay-agent.exe sync --skills-root ../skills-repo
```

## NEC 部署

```bash
bash scripts/deploy-nec.sh
# NEC_HOST=127.0.0.1 NEC_USER=zuens2020
```

- 本机 API：`http://127.0.0.1:8740`（compose 绑定 loopback）
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
