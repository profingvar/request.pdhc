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
        'version': '1.0.0',
        'name': 'RequestPDHCCapabilityStatement',
        'title': 'request.pdhc Unified Service',
        'status': 'active',
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'publisher': 'PDHC',
        'description': (
            'Unified service for patient lifecycle, CarePlan readout/parse/export, '
            'and CarePlan dispatch operations.'
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
                'description': 'Authentication via SSO (sso.pdhc.se). Supports session and Bearer token.',
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
            ],
        }],
    }), 200
