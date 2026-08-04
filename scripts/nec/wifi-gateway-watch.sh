#!/usr/bin/env bash# Auto-reconnect WiFi when gateway is unreachable (fixes zombie WiFi on NEC).
set -euo pipefail

IFACE="${WIFI_IFACE:-wlo1}"
CONN="${WIFI_CONN:-CU_Gqat}"
GATEWAY="${WIFI_GATEWAY:-}"
PING_COUNT="${WIFI_PING_COUNT:-2}"
PING_TIMEOUT="${WIFI_PING_TIMEOUT:-2}"
COOLDOWN_SEC="${WIFI_COOLDOWN_SEC:-120}"
LOG_FILE="${WIFI_WATCH_LOG:-$HOME/.local/log/wifi-gateway-watch.log}"
MIHOMO_RESTART="${WIFI_RESTART_MIHOMO:-1}"

mkdir -p "$(dirname "$LOG_FILE")"
LOCK_FILE="/tmp/wifi-gateway-watch.lock"
COOLDOWN_FILE="/tmp/wifi-gateway-watch.cooldown"

log() {
  printf '%s %s\n' "$(date -Is)" "$*" | tee -a "$LOG_FILE"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  exit 0
fi

if [[ -f "$COOLDOWN_FILE" ]]; then
  last=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
  now=$(date +%s)
  if (( now - last < COOLDOWN_SEC )); then
    exit 0
  fi
fi

if ! ip link show "$IFACE" &>/dev/null; then
  exit 0
fi

state=$(nmcli -g GENERAL.STATE dev show "$IFACE" 2>/dev/null || true)
if [[ "$state" != *"connected"* ]]; then
  log "WiFi $IFACE not connected (state=$state), bringing up $CONN"
  nmcli con up "$CONN" || log "Failed to bring up $CONN"
  date +%s > "$COOLDOWN_FILE"
  exit 0
fi

if [[ -z "$GATEWAY" ]]; then
  GATEWAY=$(nmcli -g IP4.GATEWAY dev show "$IFACE" 2>/dev/null | head -1)
fi
if [[ -z "$GATEWAY" ]]; then
  GATEWAY="192.168.0.1"
fi

if ping -I "$IFACE" -c "$PING_COUNT" -W "$PING_TIMEOUT" "$GATEWAY" &>/dev/null; then
  exit 0
fi

log "Gateway $GATEWAY unreachable on $IFACE, reconnecting $CONN"
nmcli con down "$CONN" &>/dev/null || true
sleep 2
if nmcli con up "$CONN"; then
  log "Reconnected $CONN successfully"
  sleep 4
  if ping -I "$IFACE" -c 2 -W 3 "$GATEWAY" &>/dev/null; then
    log "Gateway $GATEWAY is reachable again"
    if [[ "$MIHOMO_RESTART" == "1" ]]; then
      if ! curl -sf --max-time 8 -x "http://127.0.0.1:7890" https://www.gstatic.com/generate_204 -o /dev/null; then
        log "Proxy still down after WiFi fix, restarting mihomo"
        systemctl --user restart mihomo || true
        sleep 3
        if curl -sf --max-time 10 -x "http://127.0.0.1:7890" https://www.gstatic.com/generate_204 -o /dev/null; then
          log "mihomo proxy recovered"
        else
          log "WARNING: mihomo proxy still unreachable after restart"
        fi
      fi
    fi
  else
    log "WARNING: gateway still unreachable after reconnect"
  fi
else
  log "ERROR: failed to reconnect $CONN"
fi

date +%s > "$COOLDOWN_FILE"
