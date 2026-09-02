"""Tests for the auto-complete internal endpoint.

POST /api/v1/internal/service-request/<sr>/complete flips the provider
contract-match to 'completed' so the provider feed reflects clinical
completion (gateway calls this when an accepted report marks the SR done).
"""
import uuid

SERVICE_KEY = 'test-internal-service-key-12345'


def svc_headers():
    return {'X-Service-Key': SERVICE_KEY, 'Content-Type': 'application/json'}


def _seed_sr_with_match(app, match_status='sent'):
    from app import db
    from app.models.service_request_models import (
        ServiceRequest, ServiceRequestContractMatch,
    )
    sr_guid = str(uuid.uuid4())
    patient_guid = str(uuid.uuid4())
    provider_org = str(uuid.uuid4())
    contract = str(uuid.uuid4())
    with app.app_context():
        db.session.add(ServiceRequest(
            guid=sr_guid, status='active', patient_guid=patient_guid,
            plan_definition_guid=str(uuid.uuid4()),
            requester_user_guid=str(uuid.uuid4()),
            requester_user_name='Dr. Test',
            requester_org_guid=str(uuid.uuid4()),
            requester_org_name='Test Org',
            contract_guid=contract,
        ))
        m = ServiceRequestContractMatch(
            service_request_guid=sr_guid, contract_guid=contract,
            provider_org_guid=provider_org, match_type='push',
            status=match_status,
        )
        db.session.add(m)
        db.session.commit()
        return sr_guid, m.guid


def _match_status(app, mguid):
    from app.models.service_request_models import ServiceRequestContractMatch
    with app.app_context():
        return ServiceRequestContractMatch.query.filter_by(guid=mguid).first().status


class TestAutoComplete:

    def test_flips_sent_match_to_completed(self, app, client):
        sr_guid, mguid = _seed_sr_with_match(app, 'sent')
        r = client.post(
            f'/api/v1/internal/service-request/{sr_guid}/complete',
            headers=svc_headers())
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'completed'
        assert body['matches_updated'] == 1
        assert _match_status(app, mguid) == 'completed'

    def test_idempotent_noop_when_already_completed(self, app, client):
        sr_guid, mguid = _seed_sr_with_match(app, 'completed')
        r = client.post(
            f'/api/v1/internal/service-request/{sr_guid}/complete',
            headers=svc_headers())
        assert r.status_code == 200
        assert r.get_json()['matches_updated'] == 0
        assert _match_status(app, mguid) == 'completed'

    def test_does_not_resurrect_rejected(self, app, client):
        sr_guid, mguid = _seed_sr_with_match(app, 'rejected')
        r = client.post(
            f'/api/v1/internal/service-request/{sr_guid}/complete',
            headers=svc_headers())
        assert r.status_code == 200
        assert r.get_json()['matches_updated'] == 0
        assert _match_status(app, mguid) == 'rejected'

    def test_unknown_sr_returns_404(self, client):
        r = client.post(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/complete',
            headers=svc_headers())
        assert r.status_code == 404

    def test_requires_service_key(self, client):
        r = client.post(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/complete')
        assert r.status_code in (401, 403)

    def test_wrong_service_key_rejected(self, client):
        r = client.post(
            f'/api/v1/internal/service-request/{uuid.uuid4()}/complete',
            headers={'X-Service-Key': 'wrong-key'})
        assert r.status_code in (401, 403)
