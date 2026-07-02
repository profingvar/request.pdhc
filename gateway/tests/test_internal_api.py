"""Tests for internal API endpoints (items 8.1–8.5)."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

SERVICE_KEY = 'test-internal-service-key-12345'


def svc_headers():
    return {'X-Service-Key': SERVICE_KEY, 'Content-Type': 'application/json'}


# ── Helpers ──────────────────────────────────────────────────────────


def _create_sr(app):
    """Create a ServiceRequest with a plan_definition_snapshot +
    transactions. Ticket #380 (rollup #348) — refreshed to match the
    shape context_service.get_sr_context now reads from. Previously
    the test seeded transactions inside fhir_resource.contained[0]
    ._pdhc_transactions; the service reads from
    plan_definition_snapshot.activities[i].transactions[j]."""
    from app import db
    from app.models.service_request_models import ServiceRequest

    sr_guid = str(uuid.uuid4())
    patient_guid = str(uuid.uuid4())
    concept_a = str(uuid.uuid4())
    tx_a = str(uuid.uuid4())
    goal_guid = str(uuid.uuid4())

    sr = ServiceRequest(
        guid=sr_guid,
        status='active',
        patient_guid=patient_guid,
        plan_definition_guid=str(uuid.uuid4()),
        requester_user_guid=str(uuid.uuid4()),
        requester_user_name='Dr. Test',
        requester_org_guid=str(uuid.uuid4()),
        requester_org_name='Test Org',
        contract_guid=str(uuid.uuid4()),
        plan_definition_snapshot={
            'goals': [{
                'guid': goal_guid,
                'concept_guid': concept_a,
                'concept_name': 'Spirometri',
            }],
            'activities': [{
                'goal_guid': goal_guid,
                'goal_concept_guid': concept_a,
                'goal_concept_name': 'Spirometri',
                'transactions': [{
                    'guid': tx_a,
                    'concept_guid': concept_a,
                    'concept_name': 'Spirometri',
                    'unit': 'percent',
                    'unit_display': '% predicted',
                    'expected_value': '80',
                    'range_min': 70.0,
                    'range_max': 120.0,
                    'requirement_type': 'required',
                }],
            }],
        },
        fhir_resource={
            'resourceType': 'ServiceRequest',
            'contained': [
                {
                    'resourceType': 'Goal',
                    'description': {
                        'text': 'Uppna astmakontroll',
                        'coding': [{'code': concept_a}],
                    },
                    'priority': {'text': 'high'},
                    'target': [{'detailQuantity': {'value': 70.0, 'comparator': '>='}}],
                },
            ],
        },
    )
    contract_guid = sr.contract_guid
    org_guid = sr.requester_org_guid
    with app.app_context():
        db.session.add(sr)
        db.session.commit()
    return sr_guid, patient_guid, concept_a, tx_a, contract_guid, org_guid


def _create_grant(app, sr_guid, patient_guid, org_guid, contract_guid):
    """Issue a DataExchangeGrant for testing."""
    with app.app_context():
        from app.services.grant_service import issue_grant
        result, status = issue_grant(
            service_request_guid=sr_guid,
            patient_guid=patient_guid,
            provider_org_guid=org_guid,
            contract_guid=contract_guid,
        )
        return result['grant_token']


# ── Service key auth ─────────────────────────────────────────────────


class TestServiceKeyAuth:
    def test_missing_key_rejected(self, client):
        r = client.get(f'/api/v1/internal/service-request/{uuid.uuid4()}/context')
        assert r.status_code == 401
        assert r.json['error'] == 'unauthorized'

    def test_invalid_key_rejected(self, client):
        r = client.get(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/context',
            headers={'X-Service-Key': 'wrong-key'},
        )
        assert r.status_code == 401

    def test_valid_key_accepted(self, client):
        # Will get 404 (SR not found) but not 401
        r = client.get(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/context',
            headers=svc_headers(),
        )
        assert r.status_code == 404


# ── SR context endpoint ──────────────────────────────────────────────


class TestSRContext:
    def test_returns_context(self, app, client):
        sr_guid, patient_guid, concept_a, tx_a, contract_guid, org_guid = _create_sr(app)

        r = client.get(
            f'/api/v1/internal/service-request/{sr_guid}/context',
            headers=svc_headers(),
        )
        assert r.status_code == 200
        data = r.json
        assert data['service_request_guid'] == sr_guid
        assert data['patient_guid'] == patient_guid
        assert data['contract_guid'] == contract_guid
        assert data['status'] == 'active'
        assert len(data['transactions']) == 1
        assert data['transactions'][0]['transaction_guid'] == tx_a
        assert data['transactions'][0]['concept_guid'] == concept_a
        assert data['transactions'][0]['concept_name'] == 'Spirometri'
        assert data['transactions'][0]['range_min'] == 70.0
        assert len(data['goals']) == 1
        assert data['goals'][0]['description'] == 'Uppna astmakontroll'

    def test_not_found(self, client):
        r = client.get(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/context',
            headers=svc_headers(),
        )
        assert r.status_code == 404

    def test_sr_without_fhir_resource(self, app, client):
        """SR with no fhir_resource should still return metadata."""
        from app import db
        from app.models.service_request_models import ServiceRequest

        sr_guid = str(uuid.uuid4())
        sr = ServiceRequest(
            guid=sr_guid,
            status='draft',
            patient_guid=str(uuid.uuid4()),
            plan_definition_guid=str(uuid.uuid4()),
            requester_user_guid=str(uuid.uuid4()),
        )
        with app.app_context():
            db.session.add(sr)
            db.session.commit()

        r = client.get(
            f'/api/v1/internal/service-request/{sr_guid}/context',
            headers=svc_headers(),
        )
        assert r.status_code == 200
        assert r.json['transactions'] == []
        assert r.json['goals'] == []


# ── Grant validation endpoint ────────────────────────────────────────


class TestGrantValidation:
    def test_valid_grant(self, app, client):
        sr_guid, patient_guid, _, _, contract_guid, org_guid = _create_sr(app)
        grant_token = _create_grant(app, sr_guid, patient_guid, org_guid, contract_guid)

        r = client.post('/api/v1/internal/grant/validate', headers=svc_headers(), json={
            'sr_guid': sr_guid,
            'patient_guid': patient_guid,
            'org_guid': org_guid,
            'contract_guid': contract_guid,
            'grant_token': grant_token,
        })
        assert r.status_code == 200
        assert r.json['valid'] is True
        assert r.json['contract_guid'] == contract_guid

    def test_invalid_grant_token(self, app, client):
        sr_guid, patient_guid, _, _, contract_guid, org_guid = _create_sr(app)
        _create_grant(app, sr_guid, patient_guid, org_guid, contract_guid)

        r = client.post('/api/v1/internal/grant/validate', headers=svc_headers(), json={
            'sr_guid': sr_guid,
            'patient_guid': patient_guid,
            'org_guid': org_guid,
            'contract_guid': contract_guid,
            'grant_token': 'fake-token',
        })
        assert r.status_code == 200
        assert r.json['valid'] is False

    def test_missing_fields(self, client):
        r = client.post('/api/v1/internal/grant/validate', headers=svc_headers(), json={
            'sr_guid': str(uuid.uuid4()),
        })
        assert r.status_code == 400
        assert r.json['valid'] is False
        assert 'Missing' in r.json['error']

    def test_wrong_patient(self, app, client):
        sr_guid, patient_guid, _, _, contract_guid, org_guid = _create_sr(app)
        grant_token = _create_grant(app, sr_guid, patient_guid, org_guid, contract_guid)

        r = client.post('/api/v1/internal/grant/validate', headers=svc_headers(), json={
            'sr_guid': sr_guid,
            'patient_guid': str(uuid.uuid4()),  # wrong patient
            'org_guid': org_guid,
            'contract_guid': contract_guid,
            'grant_token': grant_token,
        })
        assert r.status_code == 200
        assert r.json['valid'] is False

    def test_auth_required(self, client):
        r = client.post('/api/v1/internal/grant/validate', json={'sr_guid': 'x'})
        assert r.status_code == 401
