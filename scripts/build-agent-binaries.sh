#!/usr/bin/env bash
# Cross-compile relay-agent into packages/mcp-relay-*/bin/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENT="$ROOT/agent"
VER="${VERSION:-0.2.0}"

build() {
  local goos="$1" goarch="$2" pkg="$3" outname="$4"
  local dir="$ROOT/packages/$pkg/bin"
  mkdir -p "$dir"
  local out="$dir/$outname"
  echo "==> $goos/$goarch -> $out"
  (cd "$AGENT" && CGO_ENABLED=0 GOOS="$goos" GOARCH="$goarch" go build -ldflags "-s -w" -o "$out" ./cmd/relay-agent)
  # bump package version if present
  if command -v node >/dev/null 2>&1; then
    node -e "const fs=require('fs');const p='$ROOT/packages/$pkg/package.json';const j=JSON.parse(fs.readFileSync(p,'utf8'));j.version='$VER';fs.writeFileSync(p,JSON.stringify(j,null,2)+'\n')"
  fi
}

build windows amd64 mcp-relay-win32-x64 relay-agent.exe
build darwin amd64 mcp-relay-darwin-x64 relay-agent
build darwin arm64 mcp-relay-darwin-arm64 relay-agent
build linux amd64 mcp-relay-linux-x64 relay-agent

# sync main package version
if command -v node >/dev/null 2>&1; then
  node -e "const fs=require('fs');const p='$ROOT/packages/mcp-relay/package.json';const j=JSON.parse(fs.readFileSync(p,'utf8'));j.version='$VER';for (const k of Object.keys(j.optionalDependencies||{})) j.optionalDependencies[k]='$VER';fs.writeFileSync(p,JSON.stringify(j,null,2)+'\n')"
fi

echo "Done. Binaries under packages/mcp-relay-*/bin/"
