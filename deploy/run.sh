#!/bin/sh
# Keeps read-only copies of one or more issue hubs (and, optionally,
# issue-hub-board itself) fresh from git, and serves the viewer for all of them.
#
#   HUBS            space-separated git sources, one per hub: URLs or paths (required)
#   BOARD_SOURCE    git source for issue-hub-board; unset uses the copy in this image
#   BRANCH          branch to follow in every repo (default main)
#   SYNC_INTERVAL   seconds between pulls (default 120)
#   HOST, PORT      where the viewer listens (default 0.0.0.0:8788)
#   DATA            working folder (default /data)
#
# The viewer re-exports a hub whenever its files change; a board update
# restarts the viewer.
set -eu

: "${HUBS:?set HUBS to one or more git sources}"
INTERVAL=${SYNC_INTERVAL:-120}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8788}
BRANCH=${BRANCH:-main}
DATA=${DATA:-/data}
export HOME="$DATA/home"
mkdir -p "$HOME" "$DATA/hubs"
git config --global safe.directory '*'

sync() {
  if [ -d "$2/.git" ]; then
    git -C "$2" fetch -q origin "$BRANCH" && git -C "$2" reset -q --hard "origin/$BRANCH"
  else
    git clone -q --branch "$BRANCH" "$1" "$2"
  fi
}

folder() { echo "$DATA/hubs/$(basename "$1" .git)"; }
board_dir() { if [ -n "${BOARD_SOURCE:-}" ]; then echo "$DATA/board"; else echo /app; fi; }
board_rev() { git -C "$(board_dir)" rev-parse --short HEAD 2>/dev/null || echo image; }

sync_all() {
  for src in $HUBS; do
    sync "$src" "$(folder "$src")" || echo "sync failed for $(basename "$src" .git)" >&2
  done
  if [ -n "${BOARD_SOURCE:-}" ]; then
    sync "$BOARD_SOURCE" "$DATA/board" || echo "board sync failed" >&2
  fi
}

start() {
  set --
  for src in $HUBS; do set -- "$@" "$(folder "$src")"; done
  python3 -B "$(board_dir)/issue-hub-board" view "$@" \
    --out "$DATA/site" --host "$HOST" --port "$PORT" --no-open &
  PID=$!
  REV=$(board_rev)
  echo "viewer started on $HOST:$PORT for $(echo $HUBS | wc -w) hub(s), board $REV"
}

sync_all
trap 'kill "$PID" 2>/dev/null; exit 0' TERM INT
start

while sleep "$INTERVAL" & wait $!; do
  sync_all
  if [ "$(board_rev)" != "$REV" ] || ! kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
    start
  fi
done
