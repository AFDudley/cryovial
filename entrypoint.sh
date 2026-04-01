#!/bin/bash
set -euo pipefail

COORD_GIT_DIR="/home/exophial/coord.git"
LOG_DIR="/var/log/exophial"
mkdir -p "$LOG_DIR"

# ── Initialize coord.git bare repo if needed ──
if [ ! -f "$COORD_GIT_DIR/HEAD" ]; then
    echo "[entrypoint] Initializing coord.git bare repo"
    git init --bare "$COORD_GIT_DIR"
    chown -R exophial:exophial "$COORD_GIT_DIR"
fi

# ── Sync from backup remote if configured ──
if [ -n "${COORD_GIT_BACKUP_URL:-}" ]; then
    echo "[entrypoint] Syncing coord.git from backup: $COORD_GIT_BACKUP_URL"
    cd "$COORD_GIT_DIR"
    git remote add backup "$COORD_GIT_BACKUP_URL" 2>/dev/null || true
    git fetch backup --prune 2>/dev/null || echo "[entrypoint] Warning: backup fetch failed, continuing with local state"
    cd /
fi

# ── Start image-watcher ──
if [ -n "${EXOPHIAL_WATCH_CONFIG:-}" ]; then
    echo "[entrypoint] Starting image-watcher"
    exophial image-watcher --config "$EXOPHIAL_WATCH_CONFIG" \
        >>"$LOG_DIR/image-watcher.log" 2>&1 &
    IMAGE_WATCHER_PID=$!
    echo "[entrypoint] Image watcher started (PID: $IMAGE_WATCHER_PID)"
else
    echo "[entrypoint] No EXOPHIAL_WATCH_CONFIG set, image-watcher disabled"
fi

# ── Start exophial-cluster MCP server ──
# Invoked per-connection via SSH, not as a daemon.
echo "[entrypoint] exophial-cluster MCP server available via SSH"

echo "[entrypoint] Cryovial container ready"

# ── Start sshd in foreground (PID 1 replacement) ──
# exec replaces bash with sshd so signals (SIGTERM) are delivered directly.
# -D keeps sshd in foreground. Container exits when sshd exits.
exec /usr/sbin/sshd -D -e 2>>"$LOG_DIR/sshd.log"
