#!/bin/bash
# start.sh — Single entry-point for request.pdhc (Rule 16)
# Ports: 9060 (Flask), 9061 (PostgreSQL), 9062-9063 (reserved)
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_DIR="$SCRIPT_DIR/gateway"

echo "=== request.pdhc startup ==="

# 1. Kill any processes on project ports
echo "Checking ports 9060-9063..."
for port in 9060 9061 9062 9063; do
    pid=$(lsof -ti :$port 2>/dev/null || true)
    if [ -n "$pid" ]; then
        echo "  Killing process on port $port (PID: $pid)"
        kill -9 $pid 2>/dev/null || true
    fi
done
echo "  Ports cleared."

# 2. Ensure Docker is running
echo "Checking Docker..."
if ! docker info >/dev/null 2>&1; then
    echo "  Docker not running. Attempting to start..."
    if command -v colima >/dev/null 2>&1; then
        echo "  Starting Colima..."
        colima start 2>/dev/null || true
        sleep 3
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "  Trying Docker Desktop..."
        open -a Docker 2>/dev/null || true
        echo "  Waiting for Docker Desktop to start..."
        for i in $(seq 1 30); do
            if docker info >/dev/null 2>&1; then
                break
            fi
            sleep 2
        done
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "ERROR: Docker is not running and could not be started."
        exit 1
    fi
fi
echo "  Docker is running."

# 3. Activate virtual environment
echo "Activating virtual environment..."
if [ ! -d "$GATEWAY_DIR/venv" ]; then
    echo "  Creating venv..."
    python3 -m venv "$GATEWAY_DIR/venv"
fi
source "$GATEWAY_DIR/venv/bin/activate"
echo "  Installing dependencies..."
pip install -q -r "$GATEWAY_DIR/requirements.txt"

# 4. Start Docker services
echo "Starting Docker services..."
cd "$GATEWAY_DIR"
docker compose up -d --build

# 5. Wait for health checks
echo "Waiting for services to be healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:9060/api/health >/dev/null 2>&1; then
        echo "  Application is healthy!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "  Warning: Health check not passing yet. Check logs."
    fi
    sleep 2
done

echo ""
echo "=== request.pdhc is running ==="
echo "  App:      http://localhost:9060"
echo "  Database: localhost:9061"
echo "  Health:   http://localhost:9060/api/health"
echo ""
echo "Press Ctrl+C to stop..."

# 6. Tail logs; Ctrl+C triggers graceful shutdown
trap 'echo ""; echo "Shutting down..."; cd "$GATEWAY_DIR" && docker compose down; deactivate 2>/dev/null; echo "Stopped."; exit 0' INT TERM

docker compose logs -f
