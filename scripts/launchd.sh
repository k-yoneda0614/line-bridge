#!/usr/bin/env bash
# Manage the two launchd agents: Synapse and the LINE bridge.
# Usage: launchd.sh install [synapse|bridge|all]|uninstall|restart|status
source "$(dirname "$0")/common.sh"

AGENTS_DIR="$HOME/Library/LaunchAgents"
UID_DOMAIN="gui/$(id -u)"
SYNAPSE_LABEL="$LAUNCHD_PREFIX.synapse"
BRIDGE_LABEL="$LAUNCHD_PREFIX.bridge"

write_plist() {
  local label=$1 workdir=$2 name=$3; shift 3
  local args=""
  for a in "$@"; do args+="    <string>$a</string>"$'\n'; done
  cat >"$AGENTS_DIR/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
$args  </array>
  <key>WorkingDirectory</key><string>$workdir</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <!-- 0077: databases and logs created by the services stay owner-only. -->
  <key>Umask</key><integer>63</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/$name.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/$name.err.log</string>
</dict>
</plist>
EOF
}

boot_out() {
  launchctl bootout "$UID_DOMAIN/$1" 2>/dev/null || true
  # bootout returns before the job is gone; bootstrapping too early fails with EIO.
  for _ in $(seq 1 50); do
    launchctl print "$UID_DOMAIN/$1" >/dev/null 2>&1 || return 0
    sleep 0.2
  done
}
boot_in() { launchctl bootstrap "$UID_DOMAIN" "$AGENTS_DIR/$1.plist"; }

case "${1:-status}" in
  install)
    mkdir -p "$AGENTS_DIR" "$LOG_DIR"
    write_plist "$SYNAPSE_LABEL" "$SYNAPSE_DIR" synapse \
      "$VENV/bin/python" -m synapse.app.homeserver -c "$SYNAPSE_DIR/homeserver.yaml"
    write_plist "$BRIDGE_LABEL" "$BRIDGE_DIR" bridge \
      "$BRIDGE_BIN" -c "$BRIDGE_DIR/config.yaml" -r "$BRIDGE_DIR/registration.yaml"
    case "${2:-all}" in
      synapse) targets=("$SYNAPSE_LABEL") ;;
      bridge) targets=("$BRIDGE_LABEL") ;;
      all) targets=("$SYNAPSE_LABEL" "$BRIDGE_LABEL") ;;
      *) die "unknown target: $2" ;;
    esac
    for l in "${targets[@]}"; do boot_out "$l"; boot_in "$l"; log "loaded: $l"; done
    ;;
  uninstall)
    for l in "$BRIDGE_LABEL" "$SYNAPSE_LABEL"; do boot_out "$l"; rm -f "$AGENTS_DIR/$l.plist"; done
    log "uninstalled"
    ;;
  restart)
    for l in "$SYNAPSE_LABEL" "$BRIDGE_LABEL"; do launchctl kickstart -k "$UID_DOMAIN/$l"; done
    ;;
  status)
    for l in "$SYNAPSE_LABEL" "$BRIDGE_LABEL"; do
      if launchctl print "$UID_DOMAIN/$l" >/dev/null 2>&1; then
        state=$(launchctl print "$UID_DOMAIN/$l" | awk -F'= ' '/^\tstate/ {print $2; exit}')
        echo "$l: ${state:-loaded}"
      else
        echo "$l: not loaded"
      fi
    done
    ;;
  *) die "usage: $0 install [synapse|bridge|all]|uninstall|restart|status" ;;
esac
