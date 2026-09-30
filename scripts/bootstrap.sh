#!/usr/bin/env bash
# One-shot, idempotent setup: build the bridge, install Synapse, write configs,
# register with launchd, and create the local Matrix user.
source "$(dirname "$0")/common.sh"

command -v go >/dev/null || die "go is required: brew install go"
command -v uv >/dev/null || die "uv is required: brew install uv"
command -v cargo >/dev/null || die "Rust is required to build Synapse from source: brew install rust"

umask 077
mkdir -p "$DATA_DIR" "$SYNAPSE_DIR" "$BRIDGE_DIR" "$LOG_DIR"

# 1. Bridge binary: pinned upstream commit + our own patches (patches/*.patch).
if [ ! -d "$BRIDGE_SRC/.git" ]; then
  log "clone $BRIDGE_REPO"
  mkdir -p "$(dirname "$BRIDGE_SRC")"
  git clone -q "$BRIDGE_REPO" "$BRIDGE_SRC"
fi
(
  cd "$BRIDGE_SRC"
  if [ "$(git rev-parse HEAD)" != "$BRIDGE_COMMIT" ]; then
    # Take our patches off before moving to the new commit.
    for patch in "$REPO_DIR"/patches/*.patch; do
      git apply --reverse --check "$patch" 2>/dev/null && git apply --reverse "$patch"
    done
    git diff --quiet || die "matrix-line has uncommitted changes; review them and run again"
    git fetch -q origin
    git -c advice.detachedHead=false checkout -q "$BRIDGE_COMMIT"
  fi
  for patch in "$REPO_DIR"/patches/*.patch; do
    if git apply --reverse --check "$patch" 2>/dev/null; then
      continue  # already applied
    fi
    log "apply $(basename "$patch")"
    git apply "$patch"
  done
  log "build matrix-line (${BRIDGE_COMMIT:0:7} + patches)"
  mautrix_version=$(grep 'maunium.net/go/mautrix ' go.mod | awk '{print $2}' | head -n1)
  # goolm: pure-Go olm, so libolm is not needed (encryption is disabled anyway).
  go build -tags goolm -ldflags="-s -w -X main.Commit=$(git rev-parse HEAD) -X 'main.BuildTime=$(date -Iseconds)' -X 'maunium.net/go/mautrix.GoModVersion=$mautrix_version'" ./cmd/matrix-line
)

# 2. Synapse. The PyPI wheel's Rust extension fails to load on macOS 27
#    ("mis-aligned LINKEDIT string pool"), and so does a source build with the
#    default strip; building from source without strip works.
if [ ! -x "$VENV/bin/python" ]; then
  log "create venv (python 3.12)"
  uv venv -q --python 3.12 "$VENV"
fi
if ! "$VENV/bin/python" -c "import synapse.synapse_rust" 2>/dev/null; then
  log "build Synapse $SYNAPSE_VERSION from source (unstripped)"
  CARGO_PROFILE_RELEASE_STRIP=false uv pip install -q --no-cache --python "$VENV/bin/python" \
    --reinstall-package matrix-synapse --no-binary matrix-synapse "matrix-synapse==$SYNAPSE_VERSION"
fi
uv pip install -q --python "$VENV/bin/python" "${PY_DEPS[@]}"

# 3. Synapse config.
if [ ! -f "$SYNAPSE_DIR/homeserver.yaml" ]; then
  log "generate Synapse config"
  (cd "$SYNAPSE_DIR" && "$VENV/bin/python" -m synapse.app.homeserver \
    --server-name "$SERVER_NAME" --config-path homeserver.yaml \
    --generate-config --report-stats=no --data-directory "$SYNAPSE_DIR")
  sed -i '' 's/level: INFO/level: WARNING/' "$SYNAPSE_DIR/$SERVER_NAME.log.config"
fi
"$VENV/bin/python" "$REPO_DIR/scripts/configure.py" synapse "$DATA_DIR" "$SYNAPSE_PORT" "$BRIDGE_PORT" "$SERVER_NAME" "$MATRIX_USER"

# 4. Bridge config + appservice registration.
if [ ! -f "$BRIDGE_DIR/config.yaml" ]; then
  log "generate bridge config"
  (cd "$BRIDGE_DIR" && "$BRIDGE_BIN" -e -c config.yaml)
fi
"$VENV/bin/python" "$REPO_DIR/scripts/configure.py" bridge "$DATA_DIR" "$SYNAPSE_PORT" "$BRIDGE_PORT" "$SERVER_NAME" "$MATRIX_USER"
if [ ! -f "$BRIDGE_DIR/registration.yaml" ]; then
  log "generate appservice registration"
  (cd "$BRIDGE_DIR" && "$BRIDGE_BIN" -g -c config.yaml -r registration.yaml)
fi
chmod 600 "$BRIDGE_DIR/config.yaml" "$BRIDGE_DIR/registration.yaml"
# Nothing under the data dir should be readable by other users, including DBs and logs.
chmod -R go-rwx "$DATA_DIR"

# 5. launchd services.
"$REPO_DIR/scripts/launchd.sh" install

# 6. Wait for Synapse, then create the Matrix user.
log "wait for Synapse on 127.0.0.1:$SYNAPSE_PORT"
for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$SYNAPSE_PORT/_matrix/client/versions" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$SYNAPSE_PORT/_matrix/client/versions" >/dev/null || die "Synapse did not start; see $LOG_DIR/synapse.err.log"
"$VENV/bin/python" "$REPO_DIR/scripts/create_user.py" "$DATA_DIR" "$SYNAPSE_PORT" "$SERVER_NAME" "$MATRIX_USER"

log "done. Next, log in to LINE: $VENV/bin/python $REPO_DIR/scripts/login.py"
