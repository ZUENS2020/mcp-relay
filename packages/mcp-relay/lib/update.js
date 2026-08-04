"use strict";

const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");
const { relayRoot, ensureRelayRoot, loadConfig, saveConfig } = require("./config");

const PKG = "@zuens2020/mcp-relay";
const REGISTRY = process.env.NPM_CONFIG_REGISTRY || process.env.npm_config_registry || "https://registry.npmjs.org/";
const DEFAULT_CHECK_MS = 6 * 60 * 60 * 1000; // 6h

function installedVersion() {
  try {
    return require("../package.json").version;
  } catch {
    return "0.0.0";
  }
}

function statePath() {
  return path.join(relayRoot(), "update-state.json");
}

function loadState() {
  try {
    return JSON.parse(fs.readFileSync(statePath(), "utf8"));
  } catch {
    return {};
  }
}

function saveState(st) {
  ensureRelayRoot();
  fs.writeFileSync(statePath(), JSON.stringify(st, null, 2) + "\n", { mode: 0o600 });
}

function cmpSemver(a, b) {
  const pa = String(a).replace(/^v/, "").split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  const pb = String(b).replace(/^v/, "").split(/[.+-]/).map((x) => parseInt(x, 10) || 0);
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d) return d > 0 ? 1 : -1;
  }
  return 0;
}

function fetchLatestVersion() {
  return new Promise((resolve, reject) => {
    const base = REGISTRY.replace(/\/?$/, "/");
    const namePath = PKG.startsWith("@") ? PKG.replace("/", "%2F") : PKG;
    const full = new URL(namePath, base);
    const req = https.get(
      full,
      {
        headers: { Accept: "application/vnd.npm.install-v1+json" },
        timeout: 15000,
      },
      (res) => {
        let body = "";
        res.on("data", (c) => (body += c));
        res.on("end", () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`npm registry HTTP ${res.statusCode}`));
            return;
          }
          try {
            const j = JSON.parse(body);
            const ver = j["dist-tags"]?.latest || j.version;
            if (!ver) reject(new Error("no latest version in registry response"));
            else resolve(String(ver));
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on("error", reject);
    req.on("timeout", () => {
      req.destroy();
      reject(new Error("npm registry timeout"));
    });
  });
}

function autoUpdateEnabled(cfg) {
  if (process.env.MCP_RELAY_AUTO_UPDATE === "0" || process.env.MCP_RELAY_AUTO_UPDATE === "false") {
    return false;
  }
  if (process.env.MCP_RELAY_AUTO_UPDATE === "1" || process.env.MCP_RELAY_AUTO_UPDATE === "true") {
    return true;
  }
  if (cfg && cfg.auto_update === false) return false;
  return true; // default on
}

function npmInstallLatest() {
  const args = ["i", "-g", `${PKG}@latest`, "--registry", "https://registry.npmjs.org/"];
  const r = spawnSync("npm", args, { stdio: "inherit", shell: process.platform === "win32" });
  if (r.error) throw r.error;
  if (r.status !== 0) throw new Error(`npm install failed (exit ${r.status})`);
}

/**
 * @returns {Promise<{current:string, latest:string, updateAvailable:boolean, updated?:boolean, skipped?:string}>}
 */
async function checkAndMaybeUpdate(opts = {}) {
  const cfg = opts.cfg || loadConfig();
  const force = !!opts.force;
  const apply = opts.apply !== undefined ? !!opts.apply : autoUpdateEnabled(cfg);
  const current = installedVersion();
  const st = loadState();
  const now = Date.now();
  const interval = Number(process.env.MCP_RELAY_UPDATE_INTERVAL_MS) || DEFAULT_CHECK_MS;

  if (!force && st.last_check_at && now - Date.parse(st.last_check_at) < interval) {
    return {
      current,
      latest: st.last_latest || current,
      updateAvailable: !!(st.last_latest && cmpSemver(st.last_latest, current) > 0),
      skipped: "throttled",
    };
  }

  let latest;
  try {
    latest = await fetchLatestVersion();
  } catch (e) {
    st.last_check_error = String(e.message || e);
    st.last_check_at = new Date().toISOString();
    saveState(st);
    throw e;
  }

  st.last_check_at = new Date().toISOString();
  st.last_latest = latest;
  delete st.last_check_error;
  saveState(st);

  const updateAvailable = cmpSemver(latest, current) > 0;
  if (!updateAvailable) {
    return { current, latest, updateAvailable: false };
  }

  if (!apply) {
    console.error(`[mcp-relay] 发现新版本 ${latest}（当前 ${current}）。运行: mcp-relay update`);
    return { current, latest, updateAvailable: true, updated: false };
  }

  console.error(`[mcp-relay] 正在自动升级 ${current} → ${latest} …`);
  npmInstallLatest();
  st.last_updated_at = new Date().toISOString();
  st.last_updated_to = latest;
  saveState(st);

  // persist preference if missing
  if (cfg.auto_update === undefined) {
    cfg.auto_update = true;
    try {
      saveConfig(cfg);
    } catch {
      /* ignore */
    }
  }

  console.error(`[mcp-relay] 已升级到最新版。若 watch/connect 在跑，请重启该进程。`);
  return { current, latest, updateAvailable: true, updated: true };
}

function startBackgroundUpdater(opts = {}) {
  const interval = Number(process.env.MCP_RELAY_UPDATE_INTERVAL_MS) || DEFAULT_CHECK_MS;
  const tick = async () => {
    try {
      const r = await checkAndMaybeUpdate({ cfg: opts.cfg });
      if (r.updated && typeof opts.onUpdated === "function") {
        opts.onUpdated(r);
      }
    } catch (e) {
      console.error(`[mcp-relay] 更新检查失败: ${e.message || e}`);
    }
  };
  // delay first check slightly so connect/watch starts first
  const first = setTimeout(tick, opts.immediate ? 0 : 15_000);
  const timer = setInterval(tick, interval);
  if (timer.unref) timer.unref();
  if (first.unref) first.unref();
  return () => {
    clearTimeout(first);
    clearInterval(timer);
  };
}

module.exports = {
  PKG,
  installedVersion,
  cmpSemver,
  fetchLatestVersion,
  checkAndMaybeUpdate,
  startBackgroundUpdater,
  autoUpdateEnabled,
  npmInstallLatest,
};
