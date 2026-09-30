# Shared paths and ports. Sourced by the other scripts.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Upstream bridge checkout (gitignored), built in place.
BRIDGE_SRC="${LINE_BRIDGE_SRC:-$REPO_DIR/upstream/matrix-line}"
BRIDGE_BIN="$BRIDGE_SRC/matrix-line"

# Runtime data (tokens, keys, messages) lives outside the repo.
DATA_DIR="${LINE_BRIDGE_DATA:-$HOME/.local/share/line-bridge}"
VENV="$DATA_DIR/venv"
SYNAPSE_DIR="$DATA_DIR/synapse"
BRIDGE_DIR="$DATA_DIR/bridge"
LOG_DIR="$DATA_DIR/logs"

SERVER_NAME="line.local"
SYNAPSE_PORT=18408
BRIDGE_PORT=18722
# Local Matrix user. An existing install keeps the user recorded in credentials.json.
if [ -z "${LINE_BRIDGE_MATRIX_USER:-}" ] && [ -f "$DATA_DIR/credentials.json" ]; then
  LINE_BRIDGE_MATRIX_USER=$(sed -nE 's/.*"user_id": *"@([^:"]+):.*/\1/p' "$DATA_DIR/credentials.json")
fi
MATRIX_USER="${LINE_BRIDGE_MATRIX_USER:-$(id -un | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9._=-')}"

SYNAPSE_VERSION="1.160.0"
BRIDGE_REPO="https://github.com/beeper/line.git"
# Reviewed upstream commit. Bump only after reading the diff: git -C ../matrix-line log -p <old>..<new>
BRIDGE_COMMIT="9316913b1156165fa9c80f705ac8326c46fce4ef"
PY_DEPS=("mcp==2.2.0" "httpx==0.28.1" "PyYAML==6.0.3")

LAUNCHD_PREFIX="${LINE_BRIDGE_LAUNCHD_PREFIX:-local.line-bridge}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }
