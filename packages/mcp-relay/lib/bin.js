"use strict";

const fs = require("fs");
const path = require("path");

const PACKAGE_MAP = {
  "win32-x64": "@zuens2020/mcp-relay-win32-x64",
  "darwin-x64": "@zuens2020/mcp-relay-darwin-x64",
  "darwin-arm64": "@zuens2020/mcp-relay-darwin-arm64",
  "linux-x64": "@zuens2020/mcp-relay-linux-x64",
};

function platformKey() {
  const plat = process.platform;
  let arch = process.arch;
  if (arch === "x86_64") arch = "x64";
  return `${plat}-${arch}`;
}

function resolveBinary() {
  if (process.env.MCP_RELAY_BIN) {
    const p = process.env.MCP_RELAY_BIN;
    if (!fs.existsSync(p)) {
      throw new Error(`MCP_RELAY_BIN 不存在: ${p}`);
    }
    return p;
  }

  const key = platformKey();
  const pkg = PACKAGE_MAP[key];
  if (!pkg) {
    throw new Error(
      `当前平台 ${key} 尚无预编译二进制。可设置 MCP_RELAY_BIN 指向自行编译的 relay-agent。`
    );
  }

  try {
    const pkgJson = require.resolve(`${pkg}/package.json`);
    const root = path.dirname(pkgJson);
    const name = process.platform === "win32" ? "relay-agent.exe" : "relay-agent";
    const bin = path.join(root, "bin", name);
    if (!fs.existsSync(bin)) {
      throw new Error(`二进制缺失: ${bin}`);
    }
    return bin;
  } catch (e) {
    throw new Error(
      [
        `未找到平台包 ${pkg}（当前 ${key}）。`,
        "请检查 npm 安装是否完整，或改用镜像：",
        "  npm config set registry https://registry.npmmirror.com",
        "  npm i -g @zuens2020/mcp-relay",
        "也可设置 MCP_RELAY_BIN=/path/to/relay-agent 使用本地二进制。",
        e.message ? `详情: ${e.message}` : "",
      ]
        .filter(Boolean)
        .join("\n")
    );
  }
}

module.exports = { resolveBinary, platformKey, PACKAGE_MAP };
