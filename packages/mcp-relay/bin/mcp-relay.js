#!/usr/bin/env node
"use strict";

const { spawn, spawnSync } = require("child_process");
const path = require("path");
const {
  loadConfig,
  saveConfig,
  configPath,
  ensureRelayRoot,
} = require("../lib/config");
const { resolveBinary } = require("../lib/bin");
const {
  checkAndMaybeUpdate,
  startBackgroundUpdater,
  installedVersion,
} = require("../lib/update");

const argv = process.argv.slice(2);
const cmd = argv[0];

function help() {
  console.log(`mcp-relay — MCP Relay 客户端

用法:
  mcp-relay init --url <服务端 URL>
  mcp-relay config set <key> <value>
  mcp-relay config get [key]
  mcp-relay config path
  mcp-relay update [--check] [--force]
  mcp-relay doctor|detect|register|sync|connect|watch|backup|version [...]

默认同步（live）：先备份本地 MCP → 服务端为空则上传 → 再下发配置。
connect/watch 默认每 6h 检查 npm 新版本并自动升级（可用 config set auto_update false 关闭）。

环境变量:
  RELAY_URL / RELAY_MODE / RELAY_ROOT / MCP_RELAY_BIN
  MCP_RELAY_AUTO_UPDATE=0|1
  MCP_RELAY_UPDATE_INTERVAL_MS
`);
}

function parseFlag(args, name) {
  const i = args.indexOf(name);
  if (i < 0) return null;
  return args[i + 1] || null;
}

function hasFlag(args, name) {
  return args.includes(name);
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
    cfg.auto_update = cfg.auto_update !== false;
    cfg.agent_version = cfg.agent_version || installedVersion();
    saveConfig(cfg);
    console.log(`已写入 ${configPath()}`);
    console.log(`relay_url=${cfg.relay_url}`);
    runBinary(["detect"], cfg);
    return;
  }

  if (cmd === "update") {
    const checkOnly = hasFlag(argv, "--check");
    const force = hasFlag(argv, "--force");
    try {
      const r = await checkAndMaybeUpdate({
        force: true,
        apply: !checkOnly,
      });
      if (checkOnly) {
        if (r.updateAvailable) {
          console.log(`update available: ${r.current} → ${r.latest}`);
          process.exit(0);
        }
        console.log(`up to date: ${r.current}`);
        return;
      }
      if (!r.updateAvailable) {
        console.log(`已是最新版 ${r.current}`);
        return;
      }
      if (r.updated) {
        console.log(`已升级到 ${r.latest}`);
        return;
      }
      console.log(`有新版本 ${r.latest}，但未应用（auto_update=false？）`);
    } catch (e) {
      console.error(e.message || e);
      process.exit(1);
    }
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
        "auto-update": "auto_update",
        auto_update: "auto_update",
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
        "auto-update": "auto_update",
        auto_update: "auto_update",
      };
      const k = map[key] || key;
      if (k === "allow_live_writes" || k === "auto_update") {
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
      const map = {
        url: "relay_url",
        profile: "profile",
        "allow-live": "allow_live_writes",
        "auto-update": "auto_update",
      };
      const k = map[key] || key;
      delete cfg[k];
      saveConfig(cfg);
      console.log(`已清除 ${k}`);
      return;
    }
    console.error("用法: mcp-relay config get|set|unset|path");
    process.exit(2);
  }

  const cfg = loadConfig();

  // Long-running: keep Node parent for npm auto-update + child agent.
  if (cmd === "watch" || cmd === "connect") {
    let child = null;
    const stopUpdater = startBackgroundUpdater({
      cfg,
      onUpdated: () => {
        console.error("[mcp-relay] 升级完成，重启进程以加载新版本…");
        if (child && !child.killed) child.kill("SIGTERM");
        const next = spawnSync(process.execPath, [__filename, ...argv], {
          stdio: "inherit",
          env: process.env,
        });
        process.exit(next.status == null ? 1 : next.status);
      },
    });
    const code = await runBinaryAsync(argv, cfg, (c) => {
      child = c;
    });
    stopUpdater();
    process.exit(code);
  }

  // One-shot: opportunistic check (throttled), never block on failure.
  if (["sync", "doctor", "register"].includes(cmd)) {
    checkAndMaybeUpdate({ cfg, apply: false }).catch(() => {});
  }

  const code = runBinary(argv, cfg);
  process.exit(code);
}

function buildPassArgs(args, cfg) {
  const pass = [...args];
  if (
    cfg.relay_url &&
    ["register", "sync", "watch", "connect", "doctor"].includes(args[0]) &&
    !pass.includes("--relay-url")
  ) {
    pass.push("--relay-url", cfg.relay_url);
  }
  return pass;
}

function runBinary(args, cfg) {
  let bin;
  try {
    bin = resolveBinary();
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
  const r = spawnSync(bin, buildPassArgs(args, cfg), {
    stdio: "inherit",
    env: { ...process.env },
  });
  if (r.error) {
    console.error(r.error.message);
    return 1;
  }
  return r.status == null ? 1 : r.status;
}

function runBinaryAsync(args, cfg, onSpawn) {
  return new Promise((resolve) => {
    let bin;
    try {
      bin = resolveBinary();
    } catch (e) {
      console.error(e.message);
      resolve(1);
      return;
    }
    const child = spawn(bin, buildPassArgs(args, cfg), {
      stdio: "inherit",
      env: { ...process.env },
    });
    if (typeof onSpawn === "function") onSpawn(child);
    child.on("error", (err) => {
      console.error(err.message);
      resolve(1);
    });
    child.on("exit", (code, signal) => {
      if (signal) resolve(1);
      else resolve(code == null ? 1 : code);
    });
  });
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
