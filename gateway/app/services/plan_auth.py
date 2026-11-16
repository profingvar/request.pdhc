"""#931 — request.pdhc's credential for READING plan.pdhc.

plan admits `request.pdhc` as a `read_only` service key. Until #931 there
was no such door, so every read here went out unauthenticated and plan's
reads had to stay open for that reason alone.

`plan_read_headers()` returns the pair when a key is configured and `{}`
when not — an unset key reads as unset (plan's shadow log then names the
call) rather than sending a blank credential plan would refuse with 403.

READS ONLY. Never add these to a call that relies on the operator's bearer
(e.g. dispatch_service's PlanDefinition dispatch): plan's requires_role
takes the service-key branch FIRST, so a read_only key would turn the
operator's authorised write into a 403.
"""
from __future__ import annotations

from flask import current_app

DEFAULT_SOURCE = 'request.pdhc'


def plan_read_headers() -> dict:
    key = (current_app.config.get('PLAN_SERVICE_KEY') or '').strip()
    if not key:
        return {}
    src = (current_app.config.get('PLAN_SOURCE_SERVICE') or '').strip() or DEFAULT_SOURCE
    return {'X-Source-Service': src, 'X-Service-Key': key}
