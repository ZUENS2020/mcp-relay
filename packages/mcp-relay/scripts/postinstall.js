"use strict";

const fs = require("fs");
const path = require("path");
const { PACKAGE_MAP, platformKey } = require("../lib/bin");

/** Ensure platform binary is executable after npm install (Windows tarballs drop +x). */
function main() {
  if (process.platform === "win32") return;
  const key = platformKey();
  const pkg = PACKAGE_MAP[key];
  if (!pkg) return;
  try {
    const pkgJson = require.resolve(`${pkg}/package.json`);
    const name = "relay-agent";
    const bin = path.join(path.dirname(pkgJson), "bin", name);
    if (!fs.existsSync(bin)) return;
    fs.chmodSync(bin, 0o755);
  } catch {
    // optionalDependencies may be missing on unsupported platforms
  }
}

main();
