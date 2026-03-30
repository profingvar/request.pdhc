#!/usr/bin/env bash
# ============================================================
# request.pdhc — start.sh
# All-Docker service: DB + app via docker-compose.
# IMPORTANT: No kill -9 on ports — docker-compose down handles it.
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_DIR="$SCRIPT_DIR/gateway"

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

# Detect docker-compose
if command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
    DC="docker compose"
else
    echo "[Request] ERROR: No docker-compose found."
    exit 1
fi

echo "[Request] === request.pdhc starting ==="

# ── 1. Docker check ──────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
    echo "[Request] ERROR: Docker is not running."
    echo "  Run: bash /usr/local/www/restart_all.sh"
    exit 1
fi
echo "[Request] Docker OK"

# ── 2. Stop existing (docker-compose down only — no kill -9) ─
echo "[Request] Stopping existing containers..."
cd "$GATEWAY_DIR"
$DC down 2>/dev/null || true

# ── 3. Start services ────────────────────────────────────────
echo "[Request] Starting services..."
cd "$GATEWAY_DIR"
$DC up -d --build

if [ $? -ne 0 ]; then
    echo "[Request] ERROR: docker-compose up failed."
    exit 1
fi

# ── 4. Health check ──────────────────────────────────────────
echo "[Request] Waiting for services..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:9060/api/health >/dev/null 2>&1; then
        echo "[Request]   Application is healthy!"
        break
    fi
    [ "$i" -eq 30 ] && echo "[Request]   WARNING: Health check not passing yet"
    sleep 2
done

echo ""
echo "[Request] === request.pdhc is running ==="
echo "  App:      http://localhost:9060"
echo "  Database: localhost:9061"
echo "  Health:   http://localhost:9060/api/health"
echo "  Logs:     cd $GATEWAY_DIR && $DC logs -f"
echo "  Stop:     cd $GATEWAY_DIR && $DC down"
