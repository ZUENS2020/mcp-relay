#!/usr/bin/env bash
# Deploy MCP Relay to NEC (default LAN 127.0.0.1)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEC_HOST="${NEC_HOST:-127.0.0.1}"
NEC_USER="${NEC_USER:-zuens2020}"
REMOTE="${NEC_USER}@${NEC_HOST}"
DEST="${NEC_DEST:-~/mcp-relay}"

echo "==> Deploy MCP Relay -> ${REMOTE}:${DEST}"
ssh -o BatchMode=yes -o ConnectTimeout=15 "$REMOTE" "mkdir -p ${DEST}/data"

ZIP="$(mktemp /tmp/mcp-relay-XXXXXX.zip 2>/dev/null || echo /tmp/mcp-relay-deploy.zip)"
python3 - <<PY
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
echo "    Local on NEC: http://127.0.0.1:8740"
echo "    Tunnel:       https://example.com (see docs/cloudflare-tunnel.md)"
