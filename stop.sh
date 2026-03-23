#!/bin/bash
# stop.sh — Graceful shutdown for request.pdhc
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_DIR="$SCRIPT_DIR/gateway"

echo "=== Stopping request.pdhc ==="

# Detect docker compose command
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    COMPOSE="docker compose"
fi

cd "$GATEWAY_DIR"
$COMPOSE down 2>/dev/null || true

for port in 9060 9061 9062 9063; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "Killing process on port $port (PID: $pid)"
        kill -9 $pid 2>/dev/null || true
    fi
done

echo "Stopped."
