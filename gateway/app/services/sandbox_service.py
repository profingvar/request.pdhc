"""Sandbox go-live rehearsal, shared by the CLI and the admin API (#141, #598).

The logic lives here rather than in the Flask CLI so that
`flask provider sandbox-dispatch` and `POST /api/v1/admin/sandbox-dispatch`
can never diverge: onboard.pdhc runs in its own container and cannot shell
into request_pdhc_app, so it needs the HTTP form, but the CLI remains the
operator's path. One implementation, two renderings.

Both entry points return (result_dict, status_code). The CLI renders the
dict as the PASS/FAIL block it always printed; the API returns it as JSON.
"""
import json
import time
import uuid

from app.models.security_models import ProviderAccessToken, WebhookDelivery
from app.services import webhook_dispatcher
from app.services.webhook_secret_service import get_signing_secret

EVENT_TYPE = 'service_request.dispatched'


def resolve_webhook_url(provider_org_guid, contract_guid):
    """The provider's push endpoint from its active PAT, or None."""
    pat = ProviderAccessToken.query.filter_by(
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        status='active',
    ).first()
    return pat.push_endpoint_url if pat and pat.push_endpoint_url else None


def run_dispatch(provider_org_guid, contract_guid, concept_guids=None,
                 webhook_url=None, patient_guid='SANDBOX-PATIENT',
                 immediate=True):
    """Synthesise a dispatch event, deliver it, then replay it with the
    SAME X-PDHC-Event-Id to prove the provider de-duplicates.

    Returns (result, status_code). `result['result']` is 'PASS' or 'FAIL';
    on FAIL, `result['stage']` says which half failed.
    """
    if not webhook_url:
        webhook_url = resolve_webhook_url(provider_org_guid, contract_guid)
        if not webhook_url:
            return {
                'code': 'no_webhook_url',
                'message': ('No active PAT with push_endpoint_url; supply '
                            'webhook_url to override.'),
            }, 400

    sr_guid = f'sandbox-{uuid.uuid4()}'
    payload = {
        'event': EVENT_TYPE,
        'event_version': '1.0',
        'service_request_guid': sr_guid,
        'contract_guid': contract_guid,
        'patient_guid': patient_guid,
        'concept_guids': list(concept_guids or []),
        'priority': 'routine',
        'sandbox': True,
        'download_url': f'/api/v1/provider/download/{sr_guid}',
    }

    # ── delivery #1, through the real queue ──────────────────────────
    enqueued = webhook_dispatcher.enqueue(
        event_type=EVENT_TYPE,
        provider_org_guid=provider_org_guid,
        service_request_guid=sr_guid,
        webhook_url=webhook_url,
        payload=payload,
    )
    if immediate:
        webhook_dispatcher.tick(limit=1)

    first = WebhookDelivery.query.filter_by(guid=enqueued.guid).first()
    base = {
        'service_request_guid': sr_guid,
        'webhook_url': webhook_url,
        'provider_org_guid': provider_org_guid,
        'contract_guid': contract_guid,
        'delivery': {
            'guid': first.guid,
            'status': first.status,
            'response_code': first.last_response_code,
            'event_id': first.event_id,
        },
    }

    if first.status != WebhookDelivery.STATUS_SUCCEEDED:
        return {
            **base,
            'result': 'FAIL',
            'stage': 'first_delivery',
            'message': first.last_error or first.last_response_body_excerpt,
        }, 200

    # ── delivery #2, a replay with the same event id ─────────────────
    # The WebhookDelivery row has a uniqueness constraint on event_id, so
    # the queue is bypassed and the POST made directly. De-duplicating is
    # the provider's job; verifying that they do is ours.
    body_bytes = json.dumps(
        payload, separators=(',', ':'), sort_keys=True,
    ).encode('utf-8')
    secret = webhook_dispatcher.get_signing_secret(provider_org_guid)
    headers = {
        'Content-Type': 'application/json',
        'X-PDHC-Event-Id': first.event_id,
        'X-PDHC-Event-Type': EVENT_TYPE,
        'X-PDHC-Timestamp': str(int(time.time())),
    }
    if secret:
        headers['X-PDHC-Signature'] = webhook_dispatcher.compute_signature(
            secret, body_bytes,
        )

    try:
        resp = webhook_dispatcher.http_requests.post(
            webhook_url, data=body_bytes, headers=headers,
            timeout=webhook_dispatcher.REQUEST_TIMEOUT,
        )
        replay_code = resp.status_code
        replay_ok = 200 <= replay_code < 300
        excerpt = (resp.text or '')[:200]
    except webhook_dispatcher.http_requests.RequestException as e:
        replay_ok, replay_code, excerpt = False, None, str(e)

    base['replay'] = {
        'event_id': first.event_id,
        'response_code': replay_code,
        'ok': replay_ok,
    }

    if not replay_ok:
        return {
            **base,
            'result': 'FAIL',
            'stage': 'idempotent_replay',
            'message': (f'Provider did not return 2xx on replay — {excerpt}'),
        }, 200

    return {**base, 'result': 'PASS', 'stage': None, 'message': None}, 200


def sign_payload(provider_org_guid, body_bytes):
    """The four PDHC headers the dispatcher would send for this body.

    Lets a provider engineer check their HMAC implementation against ours
    without a live dispatch. Returns (result, status_code).
    """
    secret = get_signing_secret(provider_org_guid)
    if not secret:
        return {
            'code': 'no_signing_secret',
            'message': f'No active signing secret for org {provider_org_guid}',
        }, 404

    return {
        'headers': {
            'X-PDHC-Event-Id': str(uuid.uuid4()),
            'X-PDHC-Event-Type': EVENT_TYPE,
            'X-PDHC-Timestamp': str(int(time.time())),
            'X-PDHC-Signature': webhook_dispatcher.compute_signature(
                secret, body_bytes,
            ),
        },
        'body': body_bytes.decode('utf-8', errors='replace'),
    }, 200
