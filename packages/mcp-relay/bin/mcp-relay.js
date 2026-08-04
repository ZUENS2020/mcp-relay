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
  mcp-relay watch --daemon       # 后台运行（日志 ~/.mcp-relay/logs/watch.log）
  mcp-relay daemon status [name] # 查看后台进程状态（默认 watch）
  mcp-relay daemon stop [name]   # 停止后台进程
  mcp-relay autostart [--enable|--disable|--status]  # 开机自启（systemd/launchd/计划任务）

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

/**
 * Resolve the log file for daemon mode under ~/.mcp-relay/logs/<cmd>.log
 * (also used by the agent itself on watch/connect).
 */
function daemonLogPath(cmd) {
  const fs = require("fs");
  const logsDir = path.join(require("os").homedir(), ".mcp-relay", "logs");
  fs.mkdirSync(logsDir, { recursive: true });
  return path.join(logsDir, `${cmd}.log`);
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

  if (cmd === "daemon") {
    runDaemonControl(argv[1], argv[2]);
    return;
  }

  if (cmd === "autostart") {
    const mode = hasFlag(argv, "--disable")
      ? "disable"
      : hasFlag(argv, "--status")
      ? "status"
      : "enable";
    process.exit(autostartControl(mode));
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
    // Daemon mode: detach the agent so it keeps running after the shell closes.
    if (hasFlag(argv, "--daemon") || hasFlag(argv, "-d")) {
      runDaemon(argv, cfg);
      return;
    }
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

function runDaemonControl(sub, name) {
  const fs = require("fs");
  const os = require("os");
  const { spawnSync } = require("child_process");
  const pidFile = (n) => path.join(os.homedir(), ".mcp-relay", `${n || "watch"}.pid`);
  if (sub === "stop") {
    const target = name || "watch";
    const pf = pidFile(target);
    if (!fs.existsSync(pf)) {
      console.error(`[mcp-relay] 没有找到 ${target} 的 PID 文件 (${pf})`);
      process.exit(1);
    }
    const pid = parseInt(fs.readFileSync(pf, "utf8"), 10);
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "inherit" });
    } else {
      try {
        process.kill(pid, "SIGTERM");
      } catch (e) {
        console.error(`[mcp-relay] 停止失败: ${e.message}`);
      }
    }
    fs.unlinkSync(pf);
    console.log(`[mcp-relay] 已停止 ${target} (pid=${pid})`);
    return;
  }
  if (sub === "status") {
    const target = name || "watch";
    const pf = pidFile(target);
    if (!fs.existsSync(pf)) {
      console.log(`[mcp-relay] ${target}: 未运行`);
      return;
    }
    const pid = parseInt(fs.readFileSync(pf, "utf8"), 10);
    const alive =
      process.platform === "win32"
        ? spawnSync("tasklist", ["/FI", `PID eq ${pid}`], { encoding: "utf8" }).stdout.includes(String(pid))
        : (() => {
            try {
              process.kill(pid, 0);
              return true;
            } catch {
              return false;
            }
          })();
    console.log(`[mcp-relay] ${target}: pid=${pid} ${alive ? "运行中" : "已退出"}`);
    console.log(`[mcp-relay] 日志: ${daemonLogPath(target)}`);
    return;
  }
  console.error("用法: mcp-relay daemon stop|status [watch|connect]");
  process.exit(2);
}

/**
 * Install/remove OS autostart for `mcp-relay watch`:
 *   linux  -> systemd user unit  (~/.config/systemd/user/mcp-relay-watch.service)
 *   darwin -> launchd LaunchAgent (~/Library/LaunchAgents/com.zuens2020.mcp-relay.plist)
 *   win32  -> scheduled task (schtasks /sc onlogon, name mcp-relay-agent)
 */
function autostartControl(mode) {
  const fs = require("fs");
  const os = require("os");
  const home = os.homedir();
  const relayRoot = path.join(home, ".mcp-relay");
  const logsDir = path.join(relayRoot, "logs");
  const execPath = process.execPath;
  const script = __filename;

  if (process.platform === "linux") {
    const dir = path.join(home, ".config", "systemd", "user");
    const unitName = "mcp-relay-watch.service";
    const unit = path.join(dir, unitName);
    if (mode === "status") {
      const en = spawnSync("systemctl", ["--user", "is-enabled", unitName], { encoding: "utf8" });
      const act = spawnSync("systemctl", ["--user", "is-active", unitName], { encoding: "utf8" });
      console.log(`autostart: ${en.stdout.trim() || "not-installed"} / ${act.stdout.trim()}`);
      return 0;
    }
    if (mode === "disable") {
      spawnSync("systemctl", ["--user", "disable", unitName]);
      try { fs.unlinkSync(unit); } catch (e) {}
      console.log("已关闭开机自启（systemd user: mcp-relay-watch）");
      return 0;
    }
    fs.mkdirSync(dir, { recursive: true });
    const body = `[Unit]\nDescription=MCP Relay Watch Agent\nAfter=network-online.target\nWants=network-online.target\n\n[Service]\nExecStart="${execPath}" "${script}" watch\nRestart=always\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n`;
    fs.writeFileSync(unit, body, { mode: 0o644 });
    spawnSync("systemctl", ["--user", "daemon-reload"]);
    const r = spawnSync("systemctl", ["--user", "enable", unitName]);
    if (r.status !== 0) {
      console.error((r.stderr || "").toString() || `systemctl enable 失败 (${r.status})`);
      return 1;
    }
    console.log("已启用开机自启（systemd user: mcp-relay-watch）");
    return 0;
  }

  if (process.platform === "darwin") {
    const dir = path.join(home, "Library", "LaunchAgents");
    const label = "com.zuens2020.mcp-relay";
    const plist = path.join(dir, `${label}.plist`);
    const uid = process.getuid ? process.getuid() : 501;
    if (mode === "status") {
      const r = spawnSync("launchctl", ["print", `gui/${uid}/${label}`], { encoding: "utf8" });
      console.log(`autostart: ${fs.existsSync(plist) ? "installed" : "not-installed"} / ${r.status === 0 ? "loaded" : "not-loaded"}`);
      return 0;
    }
    if (mode === "disable") {
      spawnSync("launchctl", ["bootout", `gui/${uid}/${label}`]);
      try { fs.unlinkSync(plist); } catch (e) {}
      console.log("已关闭开机自启（launchd: com.zuens2020.mcp-relay）");
      return 0;
    }
    fs.mkdirSync(dir, { recursive: true });
    fs.mkdirSync(logsDir, { recursive: true });
    const log = path.join(logsDir, "watch.log");
    const xml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${label}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${execPath}</string>
    <string>${script}</string>
    <string>watch</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>${log}</string>
  <key>StandardErrorPath</key>
  <string>${log}</string>
  <key>ProcessType</key>
  <string>Background</string>
</dict>
</plist>
`;
    fs.writeFileSync(plist, xml, { mode: 0o644 });
    // Modern launchd: bootstrap; fall back to legacy load -w.
    spawnSync("launchctl", ["bootout", `gui/${uid}/${label}`]);
    const b = spawnSync("launchctl", ["bootstrap", `gui/${uid}`, plist]);
    if (b.status !== 0) {
      const l = spawnSync("launchctl", ["load", "-w", plist]);
      if (l.status !== 0) {
        console.error((b.stderr || l.stderr || "").toString() || "launchctl bootstrap/load 失败");
        return 1;
      }
    }
    console.log("已启用开机自启（launchd: com.zuens2020.mcp-relay）");
    return 0;
  }

  if (process.platform === "win32") {
    const task = "mcp-relay-agent";
    if (mode === "status") {
      const r = spawnSync("schtasks", ["/query", "/tn", task], { encoding: "utf8" });
      console.log(`autostart: ${r.status === 0 ? "installed" : "not-installed"}`);
      return 0;
    }
    if (mode === "disable") {
      const r = spawnSync("schtasks", ["/delete", "/tn", task, "/f"]);
      console.log(r.status === 0 ? "已关闭开机自启（计划任务: mcp-relay-agent）" : "计划任务不存在或删除失败");
      return 0;
    }
    const tr = `"${execPath}" "${script}" watch`;
    const r = spawnSync("schtasks", ["/create", "/tn", task, "/tr", tr, "/sc", "onlogon", "/f"]);
    if (r.status !== 0) {
      console.error((r.stderr || "").toString() || `schtasks /create 失败 (${r.status})`);
      return 1;
    }
    console.log("已启用开机自启（计划任务: mcp-relay-agent, onlogon）");
    return 0;
  }

  console.error(`autostart 暂不支持平台: ${process.platform}`);
  return 1;
}

function runDaemon(args, cfg) {
  const fs = require("fs");
  let bin;
  try {
    bin = resolveBinary();
  } catch (e) {
    console.error(e.message);
    process.exit(1);
  }
  // Strip --daemon/-d so the child doesn't re-detach (it is the daemon).
  const childArgs = buildPassArgs(args, cfg).filter(
    (a) => a !== "--daemon" && a !== "-d"
  );
  const logFile = daemonLogPath(args[0]);
  const out = fs.openSync(logFile, "a");
  const child = spawn(bin, childArgs, {
    detached: true,
    stdio: ["ignore", out, out],
    env: { ...process.env },
    windowsHide: true,
  });
  child.unref();
  fs.closeSync(out);
  // Write PID so `mcp-relay daemon stop` can find it later.
  const pidFile = path.join(require("os").homedir(), ".mcp-relay", `${args[0]}.pid`);
  fs.writeFileSync(pidFile, String(child.pid), { mode: 0o600 });
  console.log(`[mcp-relay] ${args[0]} 已在后台启动 (pid=${child.pid})`);
  console.log(`[mcp-relay] 日志: ${logFile}`);
  console.log(`[mcp-relay] 停止: mcp-relay daemon stop ${args[0]}`);
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
