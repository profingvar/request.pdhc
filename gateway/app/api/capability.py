from datetime import datetime, timezone
from flask import Blueprint, jsonify

capability_bp = Blueprint('capability', __name__)


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
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'publisher': 'PDHC',
        'description': (
            'Unified service for patient lifecycle, CarePlan readout/parse/export, '
            'CarePlan dispatch, FHIR R5 ServiceRequest workflow operations, '
            'and Questionnaire/Form distribution to external rendering services.'
        ),
        'kind': 'instance',
        'fhirVersion': '5.0.0',
        'format': ['json'],
        'rest': [{
            'mode': 'server',
            'security': {
                'service': [{
                    'coding': [{
                        'system': 'http://terminology.hl7.org/CodeSystem/restful-security-service',
                        'code': 'OAuth',
                        'display': 'SSO/OAuth token-based authentication',
                    }]
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
                    'type': 'CarePlan',
                    'profile': 'http://hl7.org/fhir/StructureDefinition/CarePlan',
                    'interaction': [
                        {'code': 'read'},
                        {'code': 'search-type'},
                    ],
                    'searchParam': [
                        {'name': 'subject', 'type': 'reference'},
                        {'name': 'status', 'type': 'token'},
                        {'name': '_count', 'type': 'number'},
                    ],
                    'operation': [
                        {
                            'name': 'dispatch',
                            'definition': 'POST /api/v1/CarePlan/{id}/dispatch',
                        },
                        {
                            'name': 'export-csv',
                            'definition': 'POST /api/v1/CarePlan/{id}/export/csv',
                        },
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
                        {
                            'name': 'update-snapshot',
                            'definition': 'PUT /api/v1/ServiceRequest/{id}/snapshot',
                            'documentation': 'Update the editable PlanDefinition snapshot (draft only).',
                        },
                        {
                            'name': 'finalize',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/finalize',
                            'documentation': (
                                'Finalize draft: snapshot attached forms (Questionnaire + render-ready), '
                                'build FHIR R5 ServiceRequest with contained CarePlan and Questionnaires, '
                                'set status to active.'
                            ),
                        },
                        {
                            'name': 'archive',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/archive',
                        },
                        {
                            'name': 'revoke',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/revoke',
                            'documentation': 'Cancel a ServiceRequest. Only if no matches are accepted.',
                        },
                        {
                            'name': 'match',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/match',
                            'documentation': 'Find matching contracts from contract.pdhc.',
                        },
                        {
                            'name': 'push',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/push',
                            'documentation': (
                                'Push to all pending matched providers. Bundle includes FHIR ServiceRequest '
                                'with contained Questionnaires plus render-ready Binary entries for each form.'
                            ),
                        },
                        {
                            'name': 'push-one',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/push/{match_guid}',
                            'documentation': 'Push to a single matched provider.',
                        },
                        {
                            'name': 'list-forms',
                            'definition': 'GET /api/v1/ServiceRequest/{id}/forms',
                            'documentation': 'List all forms attached to a ServiceRequest.',
                        },
                        {
                            'name': 'add-form',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/forms',
                            'documentation': (
                                'Attach a form (by form_guid) to a draft ServiceRequest. '
                                'The form Questionnaire and render-ready JSON are snapshotted on finalize.'
                            ),
                        },
                        {
                            'name': 'remove-form',
                            'definition': 'DELETE /api/v1/ServiceRequest/{id}/forms/{form_attachment_guid}',
                            'documentation': 'Remove an attached form from a draft ServiceRequest.',
                        },
                        {
                            'name': 'reorder-forms',
                            'definition': 'POST /api/v1/ServiceRequest/{id}/forms/reorder',
                            'documentation': 'Bulk reorder attached forms (draft only). Body: {ordered_guids: [...]}.',
                        },
                        {
                            'name': 'provider-respond',
                            'definition': 'POST /api/v1/ServiceRequest/receipt/{token}/respond',
                            'documentation': 'Provider webhook: accept/reject via receipt token (no auth).',
                        },
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
                        {
                            'name': 'form-catalogue',
                            'definition': 'GET /api/v1/Form',
                            'documentation': 'List available forms from plan.pdhc.se catalogue (proxy).',
                        },
                        {
                            'name': 'form-detail',
                            'definition': 'GET /api/v1/Form/{form_guid}',
                            'documentation': 'Get a single form definition from plan.pdhc.se (proxy).',
                        },
                    ],
                },
            ],
            'operation': [
                {
                    'name': 'request-feed',
                    'definition': 'GET /api/v1/requests?provider_guid={guid}&since={iso-datetime}',
                    'documentation': (
                        'Provider subscription feed. Returns dispatched requests '
                        'filtered by provider_guid with cursor-based pagination. '
                        'Supports X-API-Key authentication for service-to-service calls.'
                    ),
                },
                {
                    'name': 'request-status-update',
                    'definition': 'PUT /api/v1/requests/{request_guid}/status',
                    'documentation': (
                        'Provider status callback. Allows provider portals to report '
                        'acknowledged/in_progress/completed/rejected status back.'
                    ),
                },
            ],
        }],
    }), 200
