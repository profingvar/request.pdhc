#!/bin/bash
set -e

echo "Running database migrations..."
flask db upgrade || echo "No migrations to apply or migration dir not initialised yet."

echo "Starting gunicorn on port 9060..."
exec gunicorn --bind 0.0.0.0:9060 --workers 2 --timeout 120 "app:create_app()"
