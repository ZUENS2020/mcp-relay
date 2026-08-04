#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");
const {
  loadConfig,
  saveConfig,
  configPath,
  ensureRelayRoot,
} = require("../lib/config");
const { resolveBinary } = require("../lib/bin");

const argv = process.argv.slice(2);
const cmd = argv[0];

function help() {
  console.log(`mcp-relay — MCP Relay 客户端

用法:
  mcp-relay init --url <服务端 URL>
  mcp-relay config set <key> <value>
  mcp-relay config get [key]
  mcp-relay config path
  mcp-relay doctor|detect|register|sync|watch|backup|version [...]

默认同步（live）：先备份本地 MCP → 服务端为空则上传 → 再下发配置。

环境变量:
  RELAY_URL / RELAY_MODE / RELAY_ROOT / MCP_RELAY_BIN
`);
}

function parseFlag(args, name) {
  const i = args.indexOf(name);
  if (i < 0) return null;
  return args[i + 1] || null;
}

async function main() {
  if (!cmd || cmd === "-h" || cmd === "--help" || cmd === "help") {
    help();
    process.exit(cmd ? 0 : 2);
  }

  if (cmd === "init") {
    const url = parseFlag(argv, "--url") || parseFlag(argv, "-u") || process.env.RELAY_URL;
    if (!url) {
      console.error("需要 --url <服务端地址>");
      process.exit(2);
    }
    ensureRelayRoot();
    const cfg = loadConfig();
    cfg.relay_url = url.replace(/\/$/, "");
    cfg.allow_live_writes = true;
    cfg.agent_version = cfg.agent_version || "0.2.0";
    saveConfig(cfg);
    console.log(`已写入 ${configPath()}`);
    console.log(`relay_url=${cfg.relay_url}`);
    // run detect via binary if available
    runBinary(["detect"], cfg);
    return;
  }

  if (cmd === "config") {
    const sub = argv[1];
    ensureRelayRoot();
    const cfg = loadConfig();
    if (sub === "path") {
      console.log(configPath());
      return;
    }
    if (sub === "get") {
      const key = argv[2];
      if (!key) {
        console.log(JSON.stringify(cfg, null, 2));
        return;
      }
      const map = {
        url: "relay_url",
        relay_url: "relay_url",
        profile: "profile",
        "allow-live": "allow_live_writes",
        allow_live_writes: "allow_live_writes",
      };
      const k = map[key] || key;
      console.log(cfg[k] === undefined ? "" : String(cfg[k]));
      return;
    }
    if (sub === "set") {
      const key = argv[2];
      const val = argv[3];
      if (!key || val === undefined) {
        console.error("用法: mcp-relay config set <key> <value>");
        process.exit(2);
      }
      const map = {
        url: "relay_url",
        relay_url: "relay_url",
        profile: "profile",
        "allow-live": "allow_live_writes",
        allow_live_writes: "allow_live_writes",
      };
      const k = map[key] || key;
      if (k === "allow_live_writes") {
        cfg[k] = val === "true" || val === "1" || val === "yes";
      } else {
        cfg[k] = val;
      }
      saveConfig(cfg);
      console.log(`已设置 ${k}=${cfg[k]}`);
      return;
    }
    if (sub === "unset") {
      const key = argv[2];
      const map = { url: "relay_url", profile: "profile", "allow-live": "allow_live_writes" };
      const k = map[key] || key;
      delete cfg[k];
      saveConfig(cfg);
      console.log(`已清除 ${k}`);
      return;
    }
    console.error("用法: mcp-relay config get|set|unset|path");
    process.exit(2);
  }

  // proxy to Go binary
  const cfg = loadConfig();
  const code = runBinary(argv, cfg);
  process.exit(code);
}

function runBinary(args, cfg) {
  let bin;
  try {
    bin = resolveBinary();
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
  const env = { ...process.env };
  if (cfg.relay_url && !env.RELAY_URL) {
    // Go reads config.yaml; also pass via --relay-url when register/sync
  }
  const pass = [...args];
  if (
    cfg.relay_url &&
    ["register", "sync", "watch", "doctor"].includes(args[0]) &&
    !pass.includes("--relay-url")
  ) {
    pass.push("--relay-url", cfg.relay_url);
  }
  const r = spawnSync(bin, pass, { stdio: "inherit", env });
  if (r.error) {
    console.error(r.error.message);
    return 1;
  }
  return r.status == null ? 1 : r.status;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
