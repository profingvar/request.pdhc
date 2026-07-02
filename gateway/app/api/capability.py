import os
from datetime import datetime, timezone
from flask import Blueprint, jsonify

capability_bp = Blueprint('capability', __name__)

# CapabilityStatement.date must be stable across requests AND across
# gunicorn workers (ticket #367 / rollup #348). Default gunicorn config
# forks workers post-import, so `datetime.now()` at module level runs
# once per worker and consecutive requests to different workers see
# different microseconds. Using this file's mtime gives a value that's
# identical across workers (they all read the same file baked into the
# same container image) and only advances on a real image rebuild.
# See memory `infra_gunicorn_worker_fork_freezes_datetime`.
_CAPABILITYSTATEMENT_DATE = datetime.fromtimestamp(
    os.path.getmtime(__file__), tz=timezone.utc
).strftime('%Y-%m-%dT%H:%M:%SZ')


# Canonical URL scheme for operation definitions (ticket #377).
# CapabilityStatement.rest[.resource].operation.definition is
# constrained by FHIR R5 to be a canonical URL, not a shape like
# "POST /api/v1/…" (validator_cli 6.9.10 flags whitespace and the
# missing scheme). We publish canonical URLs under this base without
# committing to serving OperationDefinition resources at those URLs —
# the definitions are self-descriptive via `documentation`, and the
# canonical URL merely identifies the operation stably. See the
# rollup #348 conformance workflow (.github/workflows/conformance.yml).
#
# The `documentation` field carries the concrete "METHOD /path" line
# as its FIRST line, followed by prose. Test #372 truth test parses
# that first line to check every advertised operation resolves in
# app.url_map — so keep the "METHOD /path" prefix EXACTLY.
_OP_CANON = 'https://request.pdhc.se/api/v1/OperationDefinition/'


def _op(name, method_path, documentation):
    """Build a spec-conformant CapabilityStatement operation entry.

    The concrete REST endpoint lives on the first line of
    documentation ("METHOD /path — description"); the `definition`
    field is a canonical URL so validator_cli accepts it.
    """
    doc = f'{method_path} — {documentation}' if documentation else method_path
    return {
        'name': name,
        'definition': f'{_OP_CANON}{name}',
        'documentation': doc,
    }


@capability_bp.route('/metadata', methods=['GET'])
def capability_statement():
    """Return FHIR R5 CapabilityStatement for this service."""
    return jsonify({
        'resourceType': 'CapabilityStatement',
        'id': 'request-pdhc',
        'url': 'https://request.pdhc.se/api/v1/metadata',
        'version': '2.0.0',
        'name': 'RequestPDHCCapabilityStatement',
        'title': 'request.pdhc Unified Service',
        'status': 'active',
        'date': _CAPABILITYSTATEMENT_DATE,
        'publisher': 'PDHC',
        'description': (
            'Dispatch service for the PDHC platform. Handles patient CarePlan '
            'CRUD (#310), PlanDefinition dispatch to caregivers (HMAC-signed '
            'webhook with idempotency + DLQ + PDL consent gate), FHIR R5 '
            'ServiceRequest workflow, and Questionnaire/Form distribution to '
            'external rendering services. Not an alerting engine — threshold '
            'evaluation and DetectedIssue/Flag emission are out of scope by '
            'design (see docs/decisions/ADR-001-alerting-scope.md).'
        ),
        'kind': 'instance',
        # cpb-14: kind=instance requires `implementation`. Added in #377
        # as part of the conformance CI landing.
        'implementation': {
            'description': 'request.pdhc production instance',
            'url': 'https://request.pdhc.se/api/v1',
        },
        'fhirVersion': '5.0.0',
        'format': ['json'],
        'rest': [{
            'mode': 'server',
            'security': {
                'service': [{
                    'coding': [{
                        # R5 CodeSystem URL for Restful Security Service.
                        # The display value is constrained by the code
                        # system to the literal 'OAuth' (validator #377
                        # flags a Wrong-Display-Name error otherwise).
                        'system': 'http://hl7.org/fhir/restful-security-service',
                        'code': 'OAuth',
                        'display': 'OAuth',
                    }],
                    'text': 'SSO/OAuth token-based authentication',
                }],
                'description': 'Authentication via SSO (sso.pdhc.se). Supports session, Bearer token, and X-API-Key (service-to-service).',
            },
            'resource': [
                {
                    'type': 'Patient',
                    'profile': 'http://hl7.org/fhir/StructureDefinition/Patient',
                    'interaction': [
                        {'code': 'read'},
                        {'code': 'search-type'},
                        {'code': 'create'},
                        {'code': 'update'},
                        {'code': 'delete'},
                    ],
                    'searchParam': [
                        {'name': 'name', 'type': 'string'},
                        {'name': 'gender', 'type': 'token'},
                        {'name': 'birthdate', 'type': 'date'},
                        {'name': '_count', 'type': 'number'},
                        {'name': '_offset', 'type': 'number'},
                    ],
                },
                {
                    # #310 shipped the real patient-CarePlan API at
                    # /api/v1/careplans (lowercase). The pre-#310
                    # CarePlan block advertised a proxy to plan.pdhc's
                    # PlanDefinition (the wire-alias-era misnomer),
                    # deleted in #320. Post-#320 + #348 the block
                    # advertises the actual CRUD + custom `context`
                    # operation. See docs/decisions/ADR-001 for scope.
                    'type': 'CarePlan',
                    'profile': 'http://hl7.org/fhir/StructureDefinition/CarePlan',
                    'interaction': [
                        {'code': 'create'},
                        {'code': 'read'},
                        {'code': 'update'},
                        {'code': 'search-type'},
                    ],
                    'searchParam': [
                        {'name': 'patient_guid', 'type': 'reference'},
                        {'name': 'status', 'type': 'token'},
                    ],
                    'operation': [
                        _op(
                            'CarePlan-context',
                            'GET /api/v1/careplans/{guid}/context',
                            (
                                'Return the CarePlan alongside its resolved '
                                'PlanDefinition snapshot (concepts, '
                                'transactions, goals, timing). Read-only.'
                            ),
                        ),
                    ],
                },
                {
                    'type': 'ServiceRequest',
                    'profile': 'http://hl7.org/fhir/StructureDefinition/ServiceRequest',
                    'interaction': [
                        {'code': 'read'},
                        {'code': 'search-type'},
                        {'code': 'create'},
                    ],
                    'searchParam': [
                        {'name': 'status', 'type': 'token'},
                        {'name': 'page', 'type': 'number'},
                        {'name': 'per_page', 'type': 'number'},
                    ],
                    'operation': [
                        _op(
                            'ServiceRequest-update-snapshot',
                            'PUT /api/v1/ServiceRequest/{id}/snapshot',
                            'Update the editable PlanDefinition snapshot (draft only).',
                        ),
                        _op(
                            'ServiceRequest-finalize',
                            'POST /api/v1/ServiceRequest/{id}/finalize',
                            (
                                'Finalize draft: snapshot attached forms (Questionnaire + render-ready), '
                                'build FHIR R5 ServiceRequest with contained CarePlan and Questionnaires, '
                                'set status to active.'
                            ),
                        ),
                        _op(
                            'ServiceRequest-archive',
                            'POST /api/v1/ServiceRequest/{id}/archive',
                            'Archive a ServiceRequest.',
                        ),
                        _op(
                            'ServiceRequest-revoke',
                            'POST /api/v1/ServiceRequest/{id}/revoke',
                            'Cancel a ServiceRequest. Only if no matches are accepted.',
                        ),
                        _op(
                            'ServiceRequest-match',
                            'POST /api/v1/ServiceRequest/{id}/match',
                            'Find matching contracts from contract.pdhc.',
                        ),
                        _op(
                            'ServiceRequest-push',
                            'POST /api/v1/ServiceRequest/{id}/push',
                            (
                                'Push to all pending matched providers. Bundle includes FHIR ServiceRequest '
                                'with contained Questionnaires plus render-ready Binary entries for each form.'
                            ),
                        ),
                        _op(
                            'ServiceRequest-push-one',
                            'POST /api/v1/ServiceRequest/{id}/push/{match_guid}',
                            'Push to a single matched provider.',
                        ),
                        _op(
                            'ServiceRequest-list-forms',
                            'GET /api/v1/ServiceRequest/{id}/forms',
                            'List all forms attached to a ServiceRequest.',
                        ),
                        _op(
                            'ServiceRequest-add-form',
                            'POST /api/v1/ServiceRequest/{id}/forms',
                            (
                                'Attach a form (by form_guid) to a draft ServiceRequest. '
                                'The form Questionnaire and render-ready JSON are snapshotted on finalize.'
                            ),
                        ),
                        _op(
                            'ServiceRequest-remove-form',
                            'DELETE /api/v1/ServiceRequest/{id}/forms/{form_attachment_guid}',
                            'Remove an attached form from a draft ServiceRequest.',
                        ),
                        _op(
                            'ServiceRequest-reorder-forms',
                            'POST /api/v1/ServiceRequest/{id}/forms/reorder',
                            'Bulk reorder attached forms (draft only). Body: {ordered_guids: [...]}.',
                        ),
                        _op(
                            'ServiceRequest-provider-respond',
                            'POST /api/v1/ServiceRequest/receipt/{token}/respond',
                            'Provider webhook: accept/reject via receipt token (no auth).',
                        ),
                    ],
                },
                {
                    'type': 'Questionnaire',
                    'profile': 'http://hl7.org/fhir/StructureDefinition/Questionnaire',
                    'documentation': (
                        'Questionnaire resources are proxied from the Plan service (plan.pdhc.se) '
                        'form catalogue. Forms are attached to ServiceRequests and their FHIR '
                        'Questionnaire + render-ready JSON are frozen at finalize time. '
                        'Contained Questionnaires are delivered inside the push bundle.'
                    ),
                    'interaction': [
                        {'code': 'read'},
                        {'code': 'search-type'},
                    ],
                    'searchParam': [
                        {'name': 'page', 'type': 'number'},
                        {'name': 'per_page', 'type': 'number'},
                    ],
                    'operation': [
                        _op(
                            'Form-catalogue',
                            'GET /api/v1/Form',
                            'List available forms from plan.pdhc.se catalogue (proxy).',
                        ),
                        _op(
                            'Form-detail',
                            'GET /api/v1/Form/{form_guid}',
                            'Get a single form definition from plan.pdhc.se (proxy).',
                        ),
                    ],
                },
            ],
            'operation': [
                _op(
                    'request-feed',
                    'GET /api/v1/requests?provider_guid={guid}&since={iso-datetime}',
                    (
                        'Provider subscription feed. Returns dispatched requests '
                        'filtered by provider_guid with cursor-based pagination. '
                        'Supports X-API-Key authentication for service-to-service calls.'
                    ),
                ),
                _op(
                    'request-status-update',
                    'PUT /api/v1/requests/{request_guid}/status',
                    (
                        'Provider status callback. Allows provider portals to report '
                        'acknowledged/in_progress/completed/rejected status back.'
                    ),
                ),
            ],
        }],
    }), 200
