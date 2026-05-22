# Outbound webhook dispatcher (ticket #140)

Sends metadata-only notifications to a provider's registered webhook
URL whenever a ServiceRequest in their contract scope reaches a state
they need to know about. The actual PHI lives behind the
authenticated `/provider/download/<sr_guid>` endpoint.

## Wire shape

```
POST <webhook_url>
Content-Type: application/json
X-PDHC-Event-Id: <uuid>             # unique per delivery, used for idempotency
X-PDHC-Event-Type: <event>          # e.g. service_request.dispatched
X-PDHC-Timestamp: <unix-seconds>
X-PDHC-Signature: sha256=<hex>      # HMAC-SHA256 over the raw body
```

Body (the dispatched event):

```json
{
  "event": "service_request.dispatched",
  "event_version": "1.0",
  "service_request_guid": "…",
  "contract_guid": "…",
  "priority": "routine",
  "created_at": "…Z",
  "download_url": "/api/v1/provider/download/<sr_guid>"
}
```

The body is **metadata only** — never patient identifiers, observations,
or content. The provider fetches the FHIR Bundle via the authenticated
download URL using their PAT.

## Signing

`webhook_dispatcher.compute_signature(secret, body_bytes)` returns
`sha256=<hex>`. The dispatcher pulls the active signing secret for
the provider org via
`webhook_secret_service.get_signing_secret(org_guid)` (see #136), so
rotated secrets stop signing immediately.

**Provider-side verification:**

```python
import hmac, hashlib
expected = 'sha256=' + hmac.new(
    secret.encode(), raw_body_bytes, hashlib.sha256
).hexdigest()
ok = hmac.compare_digest(expected, request.headers['X-PDHC-Signature'])
```

During rotation, providers may accept both the old and the new
secret. PDHC always signs with the active one.

## Retry schedule

Failures (non-2xx or network error) reschedule:

| Attempt | Delay before retry |
|---|---|
| 1 | 5 s |
| 2 | 25 s |
| 3 | 2 min |
| 4 | 10 min |
| 5 | 1 h |
| 6 (final) | → dead-letter |

After dead-letter, the dispatcher files a high-priority ticket on
ticket.mitidbok via the `~/.pdhc/ticket_api_key` (or `TICKET_API_KEY`
env). Project is `request.pdhc`, title includes the org and event
type, body summarises last response code and remediation hints.

`MAX_ATTEMPTS = 6` and the backoff sequence live in
`webhook_dispatcher.BACKOFF_SECONDS`.

## State machine

`WebhookDelivery` row statuses:

- `pending` — created or rescheduled; due when `next_attempt_at <= now`.
- `in_flight` — currently being delivered (transient).
- `succeeded` — provider returned 2xx; terminal.
- `dead_letter` — retries exhausted (or no active signing secret at
  enqueue time); terminal until manually requeued.

Indexes on `status`, `next_attempt_at`, `provider_org_guid`, and
`service_request_guid` keep the dispatcher's polling query cheap.

## Idempotency

`event_id` is a UUID and is unique per delivery row. On any retry the
**same** `X-PDHC-Event-Id` is sent. Providers MUST de-dup by
`event_id` so retries (e.g. after a transient 503) don't replay
business logic.

## Enqueue

The default trigger is in `service_request_service.create_service_request`
(to be wired up — see follow-up): once an SR is committed, for every
matched provider org with an active PAT + webhook URL, call:

```python
from app.services.webhook_dispatcher import enqueue_service_request_dispatched

enqueue_service_request_dispatched(sr, provider_org_guid, webhook_url)
```

This commits a `WebhookDelivery` row with `status='pending'` and
`next_attempt_at=now()`, so the worker's next tick picks it up.

If the provider has no active signing secret, the row is enqueued
in `dead_letter` directly so the gap shows up in the DLQ instead of
silently signing with no secret.

## Worker

Start via the CLI:

```bash
flask webhook run-worker --interval 5 --limit 20
```

Add to `start.sh` (per ticket #140 DoD):

```bash
( cd "$APP_DIR" && exec ./venv/bin/flask webhook run-worker ) &
WORKER_PID=$!
echo "$WORKER_PID" > "$SHARED/webhook-worker.pid"
```

The worker runs `tick()` every `--interval` seconds. Stops gracefully
on SIGINT/SIGTERM (default click behaviour) — start.sh's shutdown
trap should `kill -TERM $WORKER_PID`.

## CLI

```
flask webhook tick [--limit N]            One-shot: process due deliveries, exit.
flask webhook run-worker [--interval S]   Long-running loop.
flask webhook list-pending                Show pending + dead-lettered rows.
flask webhook requeue --guid <guid>       Move a DLQ row back to pending.
```

## Tests

`tests/test_webhook_dispatcher.py` covers:

- HMAC signature matches provider-side recomputation
- enqueue creates a signed pending row
- enqueue with no signing secret goes straight to DLQ + files ticket
- tick on 2xx → status=succeeded
- tick on 5xx → reschedules with ~5 s backoff
- 6 consecutive failures → status=dead_letter + ticket filed
- transport error counted as failure
- signature is over the exact body the provider receives

## Wiring (#152 — landed)

`service_request_service.create_service_request` calls
`_enqueue_dispatch_webhooks(sr, contract_guid)` after the SR commits.
That helper looks up every `ProviderAccessToken` for the contract
with `status='active'` AND `delivery_mode='push'` AND a non-empty
`push_endpoint_url`, and calls
`enqueue_service_request_dispatched(sr, org_guid, url)` for each.

The fan-out is best-effort: a single bad provider's enqueue raises
through `try/except` and is logged, never rolling back the SR
commit. A provider with no active signing secret still gets a
delivery row but in `dead_letter` status, which auto-files an ops
ticket per the dispatcher's DLQ rules.

`docker-compose.yml` includes a `worker` service alongside `app` and
`db`. It uses the same image, overrides the entrypoint to
`flask webhook run-worker --interval 5`, depends on `app:
service_healthy` so migrations are done before the worker boots, and
has `restart: unless-stopped` so it survives crashes.
