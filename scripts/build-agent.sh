#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../agent"
export GOPROXY="${GOPROXY:-https://goproxy.cn,direct}"
go test ./...
go build -buildvcs=false -o relay-agent ./cmd/relay-agent
echo "built $(pwd)/relay-agent"
