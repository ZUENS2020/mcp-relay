"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");

function relayRoot() {
  return process.env.RELAY_ROOT || path.join(os.homedir(), ".mcp-relay");
}

function configPath() {
  return path.join(relayRoot(), "config.yaml");
}

function ensureRelayRoot() {
  fs.mkdirSync(path.join(relayRoot(), "backups"), { recursive: true });
  fs.mkdirSync(path.join(relayRoot(), "logs"), { recursive: true });
}

function parseSimpleYaml(text) {
  const out = {};
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^([A-Za-z0-9_]+):\s*(.*)$/);
    if (!m) continue;
    let v = m[2].trim();
    if (v === "true") v = true;
    else if (v === "false") v = false;
    else if (v.startsWith("[") && v.endsWith("]")) {
      v = v
        .slice(1, -1)
        .split(",")
        .map((x) => x.trim().replace(/^["']|["']$/g, ""))
        .filter(Boolean);
    } else {
      v = v.replace(/^["']|["']$/g, "");
    }
    out[m[1]] = v;
  }
  return out;
}

function dumpSimpleYaml(obj) {
  const lines = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      lines.push(`${k}: [${v.map((x) => JSON.stringify(String(x))).join(", ")}]`);
    } else if (typeof v === "boolean") {
      lines.push(`${k}: ${v}`);
    } else {
      lines.push(`${k}: ${String(v)}`);
    }
  }
  return lines.join("\n") + "\n";
}

function loadConfig() {
  const p = configPath();
  if (!fs.existsSync(p)) {
    return {
      relay_url: process.env.RELAY_URL || "http://127.0.0.1:8740",
      allow_live_writes: true,
      agent_version: "0.2.0",
    };
  }
  const raw = fs.readFileSync(p, "utf8");
  const cfg = parseSimpleYaml(raw);
  if (!cfg.relay_url) cfg.relay_url = process.env.RELAY_URL || "http://127.0.0.1:8740";
  if (cfg.allow_live_writes === undefined) cfg.allow_live_writes = true;
  return cfg;
}

function saveConfig(cfg) {
  ensureRelayRoot();
  fs.writeFileSync(configPath(), dumpSimpleYaml(cfg), { mode: 0o600 });
}

module.exports = {
  relayRoot,
  configPath,
  ensureRelayRoot,
  loadConfig,
  saveConfig,
};
