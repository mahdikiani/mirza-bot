#!/usr/bin/env bash
# Idempotent per-boot startup: bring up local MongoDB + Redis for the gateway.
# Safe to run repeatedly — each service is only started if not already reachable.
set -euo pipefail

MONGO_DIR="$HOME/.local/state/mongodb"
MONGO_LOG="$MONGO_DIR/mongod.log"
mkdir -p "$MONGO_DIR"

# Redis
if redis-cli ping >/dev/null 2>&1; then
  echo "start.sh: redis already running"
else
  redis-server --daemonize yes --save "" --appendonly no
  echo "start.sh: redis started"
fi

# MongoDB
if mongosh --quiet --eval 'db.runCommand({ ping: 1 })' >/dev/null 2>&1; then
  echo "start.sh: mongodb already running"
else
  mongod --dbpath "$MONGO_DIR" --bind_ip 127.0.0.1 --port 27017 \
    --logpath "$MONGO_LOG" --fork
  echo "start.sh: mongodb started"
fi

# Wait for MongoDB to accept connections before the app tries to connect.
for _ in $(seq 1 30); do
  if mongosh --quiet --eval 'db.runCommand({ ping: 1 })' >/dev/null 2>&1; then
    echo "start.sh: mongodb ready"
    break
  fi
  sleep 1
done
