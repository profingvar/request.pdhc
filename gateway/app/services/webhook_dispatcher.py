"""Outbound webhook dispatcher (ticket #140).

When a ServiceRequest is created or transitions inside a contract,
this dispatcher delivers a *metadata-only* notification to the
provider's registered webhook URL. The actual PHI lives behind the
authenticated download endpoint (`/provider/download/<sr_guid>`).

Body is signed with HMAC-SHA256 using the active webhook signing
secret for the provider org (see webhook_secret_service / #136).
Provider verifies via the `X-PDHC-Signature` header.

Retry schedule (from the provider integration guide):
  attempt 1 → immediate
  attempt 2 → +5s
  attempt 3 → +25s
  attempt 4 → +2min
  attempt 5 → +10min
  attempt 6 → +1h
  attempt 7 → dead-letter

After dead_letter, the dispatcher files an ops ticket via the
ticket.mitidbok API so the operator is notified.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone, timedelta

import requests as http_requests
from flask import current_app

from app import db
from app.models.security_models import (
    WebhookDelivery, WebhookSigningSecret,
)
from app.services.audit_service import log_event
from app.services.webhook_secret_service import (
    _decrypt, get_signing_secret,
)

logger = logging.getLogger(__name__)


# Backoff in seconds. attempt_count == 0 means "about to make the
# first attempt". After each failed attempt we look up
# BACKOFF_SECONDS[attempt_count - 1] for the next delay.
BACKOFF_SECONDS = [5, 25, 120, 600, 3600]
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1  # = 6 attempts before dead-letter

REQUEST_TIMEOUT = 15  # seconds — per-attempt HTTP timeout


# ── Signing ────────────────────────────────────────────────────────────


def compute_signature(secret, body_bytes):
    """HMAC-SHA256 hex digest of the raw body. Header form: 'sha256=<hex>'."""
    digest = hmac.new(
        secret.encode('utf-8'),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f'sha256={digest}'


# ── Enqueue ────────────────────────────────────────────────────────────


def enqueue(*, event_type, provider_org_guid, service_request_guid,
            webhook_url, payload):
    """Enqueue a webhook delivery for the dispatcher to send.

    Returns the WebhookDelivery row (committed). If the provider has
    no active signing secret, the row is still created so the failure
    is visible — but it goes straight to dead_letter so we don't
    silently retry an unsignable payload.
    """
    body_str = json.dumps(payload, separators=(',', ':'), sort_keys=True)

    secret = get_signing_secret(provider_org_guid)
    signing_row_guid = None
    if secret is not None:
        signing_row = WebhookSigningSecret.query.filter_by(
            provider_org_guid=provider_org_guid, status='active',
        ).first()
        signing_row_guid = signing_row.guid if signing_row else None
        signature = compute_signature(secret, body_str.encode('utf-8'))
        status = WebhookDelivery.STATUS_PENDING
        last_error = None
    else:
        signature = None
        status = WebhookDelivery.STATUS_DEAD_LETTER
        last_error = 'no active webhook signing secret for org'
        logger.warning(
            'enqueue webhook for org=%s but no active signing secret — '
            'going straight to dead_letter', provider_org_guid,
        )

    row = WebhookDelivery(
        event_type=event_type,
        provider_org_guid=provider_org_guid,
        service_request_guid=service_request_guid,
        webhook_url=webhook_url,
        payload_json=body_str,
        signature=signature,
        signing_secret_guid=signing_row_guid,
        status=status,
        last_error=last_error,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.session.add(row)
    db.session.commit()

    if status == WebhookDelivery.STATUS_DEAD_LETTER:
        _file_dead_letter_ticket(row, reason='no_signing_secret')

    log_event(
        action='webhook.enqueued',
        resource_type='WebhookDelivery',
        resource_guid=row.guid,
        details={
            'event_type': event_type,
            'provider_org_guid': provider_org_guid,
            'service_request_guid': service_request_guid,
            'status': row.status,
        },
    )
    return row


def enqueue_service_request_dispatched(sr, provider_org_guid, webhook_url):
    """Convenience: build the standard service_request.dispatched body.

    Per ticket #140, the body is metadata only; the provider must
    pull the FHIR Bundle via the authenticated download endpoint.
    """
    payload = {
        'event': 'service_request.dispatched',
        'event_version': '1.0',
        'service_request_guid': sr.guid if hasattr(sr, 'guid') else sr.get('guid'),
        'contract_guid': sr.contract_guid if hasattr(sr, 'contract_guid')
            else sr.get('contract_guid'),
        'priority': getattr(sr, 'priority', None)
            or (sr.get('priority') if isinstance(sr, dict) else None)
            or 'routine',
        'created_at': (
            sr.created_at.isoformat() if hasattr(sr, 'created_at')
            and sr.created_at else
            (sr.get('created_at') if isinstance(sr, dict) else None)
        ),
        'download_url': (
            f'/api/v1/provider/download/'
            f'{sr.guid if hasattr(sr, "guid") else sr.get("guid")}'
        ),
    }
    return enqueue(
        event_type='service_request.dispatched',
        provider_org_guid=provider_org_guid,
        service_request_guid=payload['service_request_guid'],
        webhook_url=webhook_url,
        payload=payload,
    )


# ── Tick (dispatcher main loop body) ───────────────────────────────────


def tick(limit=20, now=None):
    """Process up to `limit` pending deliveries that are due.

    Returns counts dict — useful for the worker logs and CLI.
    """
    now = now or datetime.now(timezone.utc)
    due = (WebhookDelivery.query
           .filter(WebhookDelivery.status == WebhookDelivery.STATUS_PENDING)
           .filter(WebhookDelivery.next_attempt_at <= now)
           .order_by(WebhookDelivery.next_attempt_at)
           .limit(limit)
           .all())

    counts = {'attempted': 0, 'succeeded': 0,
              'rescheduled': 0, 'dead_lettered': 0}
    for row in due:
        counts['attempted'] += 1
        verdict = _attempt_delivery(row)
        counts[verdict] += 1
    return counts


def _attempt_delivery(row):
    """Send the row's payload. Update state. Return 'succeeded' /
    'rescheduled' / 'dead_lettered'."""
    row.status = WebhookDelivery.STATUS_IN_FLIGHT
    db.session.commit()

    body = row.payload_json.encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-PDHC-Event-Id': row.event_id,
        'X-PDHC-Event-Type': row.event_type,
        'X-PDHC-Timestamp': str(int(time.time())),
    }
    if row.signature:
        headers['X-PDHC-Signature'] = row.signature

    last_code = None
    last_excerpt = None
    last_error = None
    try:
        resp = http_requests.post(
            row.webhook_url, data=body, headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        last_code = resp.status_code
        last_excerpt = (resp.text or '')[:1024]
        ok = 200 <= resp.status_code < 300
    except http_requests.RequestException as e:
        last_error = str(e)[:512]
        ok = False
        logger.info('webhook %s transport error: %s', row.guid, e)

    row.attempt_count += 1
    row.last_attempt_at = datetime.now(timezone.utc)
    row.last_response_code = last_code
    row.last_response_body_excerpt = last_excerpt
    row.last_error = last_error

    if ok:
        row.status = WebhookDelivery.STATUS_SUCCEEDED
        row.succeeded_at = row.last_attempt_at
        db.session.commit()
        log_event(
            action='webhook.delivered',
            resource_type='WebhookDelivery',
            resource_guid=row.guid,
            details={
                'attempt_count': row.attempt_count,
                'response_code': last_code,
            },
        )
        return 'succeeded'

    # Failed. Either reschedule or dead-letter.
    if row.attempt_count >= MAX_ATTEMPTS:
        row.status = WebhookDelivery.STATUS_DEAD_LETTER
        db.session.commit()
        log_event(
            action='webhook.dead_lettered',
            resource_type='WebhookDelivery',
            resource_guid=row.guid,
            details={
                'attempt_count': row.attempt_count,
                'last_response_code': last_code,
                'last_error': last_error,
            },
        )
        _file_dead_letter_ticket(row, reason='retries_exhausted')
        return 'dead_lettered'

    # Schedule next attempt
    delay = BACKOFF_SECONDS[row.attempt_count - 1]
    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    row.status = WebhookDelivery.STATUS_PENDING
    db.session.commit()
    return 'rescheduled'


# ── Dead-letter ops ticket ─────────────────────────────────────────────


def _file_dead_letter_ticket(row, reason):
    """File a ticket on ticket.mitidbok so operators see DLQ events.

    Best-effort — failure to file a ticket must not crash the
    dispatcher. The DB row already records the dead-letter state.
    """
    ticket_base = os.environ.get('TICKET_BASE_URL', 'https://ticket.mitidbok.se')
    api_key = (os.environ.get('TICKET_API_KEY')
               or _read_ticket_api_key_file())
    if not api_key:
        logger.warning('No TICKET_API_KEY set; cannot file DLQ ticket for %s',
                       row.guid)
        return

    title = (
        f'Webhook DLQ ({reason}): org={row.provider_org_guid} '
        f'event={row.event_type}'
    )[:200]
    body = (
        f'WebhookDelivery {row.guid} for event_id={row.event_id} '
        f'(event_type={row.event_type}, service_request_guid='
        f'{row.service_request_guid}) reached dead-letter.\n\n'
        f'Reason: {reason}\n'
        f'Provider org: {row.provider_org_guid}\n'
        f'Webhook URL: {row.webhook_url}\n'
        f'Attempts: {row.attempt_count} / {MAX_ATTEMPTS}\n'
        f'Last response code: {row.last_response_code}\n'
        f'Last error: {row.last_error}\n'
        f'Last response excerpt: {row.last_response_body_excerpt}\n\n'
        f'Diagnose: confirm the provider endpoint is reachable, '
        f'check the active signing-secret rotation state, and either '
        f"requeue the delivery (CLI: flask webhook requeue --guid {row.guid}) "
        f'or revoke the PAT if the provider is offline indefinitely.'
    )
    try:
        http_requests.post(
            f'{ticket_base}/api/tickets',
            headers={'X-API-Key': api_key,
                     'Content-Type': 'application/json'},
            json={
                'project': 'request.pdhc',
                'title': title,
                'body': body,
                'priority': 'high',
            },
            timeout=10,
        )
    except http_requests.RequestException as e:
        logger.warning('Failed to file DLQ ticket for %s: %s', row.guid, e)


def _read_ticket_api_key_file():
    """Look up ~/.pdhc/ticket_api_key (operator's saved key)."""
    path = os.path.expanduser('~/.pdhc/ticket_api_key')
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None
