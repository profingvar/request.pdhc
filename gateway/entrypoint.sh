#!/bin/bash
set -e

export FLASK_APP="wsgi:application"

echo "Running database migrations..."
flask db upgrade || echo "No migrations to apply or migration dir not initialised yet."

echo "Starting gunicorn on port 9060..."
# Access log to stdout, captured by `docker logs request_pdhc_app`
# (ticket #370, rollup #348). Format matches plan.pdhc so future
# "did anyone call this endpoint?" soaks work uniformly across services.
exec gunicorn \
    --bind 0.0.0.0:9060 \
    --workers 2 \
    --timeout 120 \
    --access-logfile - \
    --access-logformat '%(t)s %(h)s "%(r)s" %(s)s %(L)ss' \
    "wsgi:application"
