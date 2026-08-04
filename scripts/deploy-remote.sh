#!/usr/bin/env bash
# Deploy MCP Relay to a remote host over SSH.
# Required env: DEPLOY_HOST, DEPLOY_USER
# Optional: DEPLOY_DEST (default ~/mcp-relay)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

DEPLOY_HOST="${DEPLOY_HOST:?set DEPLOY_HOST}"
DEPLOY_USER="${DEPLOY_USER:?set DEPLOY_USER}"
DEST="${DEPLOY_DEST:-~/mcp-relay}"
REMOTE="${DEPLOY_USER}@${DEPLOY_HOST}"

echo "==> Deploy MCP Relay -> ${REMOTE}:${DEST}"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE" "mkdir -p ${DEST}/data"

ZIP="$(mktemp /tmp/mcp-relay-XXXXXX.zip 2>/dev/null || echo /tmp/mcp-relay-deploy.zip)"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
$PY - <<PY
import zipfile, pathlib
root = pathlib.Path(r"""$ROOT""")
out = pathlib.Path(r"""$ZIP""")
skip = {".git", "data", "__pycache__", "relay_agent"}
skip_suffix = {".exe", ".db"}
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob("*"):
        if any(part in skip for part in p.parts):
            continue
        if p.suffix in skip_suffix:
            continue
        if p.is_file():
            z.write(p, p.relative_to(root).as_posix())
print("packed", out, out.stat().st_size)
PY

scp -o BatchMode=yes "$ZIP" "${REMOTE}:${DEST}/deploy.zip"
rm -f "$ZIP"

ssh -o BatchMode=yes "$REMOTE" "cd ${DEST} && python3 -c 'import zipfile; zipfile.ZipFile(\"deploy.zip\").extractall(\".\")' && docker compose build && docker compose up -d && curl -sf http://127.0.0.1:8740/health && echo"

echo "==> Done"
echo "    Health: http://127.0.0.1:8740/health (on the remote host)"
