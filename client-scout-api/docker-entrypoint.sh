#!/bin/sh
set -eu

SNAPSHOT_PATH="${SNAPSHOT_DIR:-/app/snapshots}"

mkdir -p "$SNAPSHOT_PATH"
chown -R scout:scout "$SNAPSHOT_PATH"

exec gosu scout "$@"
