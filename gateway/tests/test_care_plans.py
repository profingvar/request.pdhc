"""Tests — CarePlan API (#310 / #294 RFC decision A1).

The patient-specific CarePlan instance. NOT to be confused with the
legacy `/api/v1/CarePlan` proxy in careplans_bp (which forwards to
plan.pdhc as a URL-level misnomer for PlanDefinition).
"""
from unittest.mock import patch
from app.models.care_plan_models import CarePlan
from app import db


def _patch_plandef(snapshot=None):
    """Mock the plan_definition_service.get_plan_definition call."""
    body = snapshot or {
        'guid': 'pd-1',
        'title': 'T1D follow-up',
        'goals': [
            {'concept_guid': 'c-1', 'target_value': 7.0,
             'target_comparator': '<', 'description': 'HbA1c < 7'},
        ],
        'activities': [
            {'guid': 'act-1', 'transactions': [
                {'guid': 'tx-1', 'concept_guid': 'c-hba1c',
                 'concept_name': 'HbA1c', 'range_min': 4.0, 'range_max': 7.0,
                 'requirement_type': 'required'},
            ]},
        ],
    }
    return patch('app.api.care_plans.plan_definition_service.get_plan_definition',
                  return_value=(body, 200))


class TestCreateCarePlan:

    def test_minimal_create(self, client):
        with _patch_plandef():
            r = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-1',
                'plan_definition_guid': 'pd-1',
            })
        assert r.status_code == 201
        body = r.get_json()
        assert body['patient_guid'] == 'pat-1'
        assert body['plan_definition_guid'] == 'pd-1'
        assert body['status'] == 'draft'
        assert body['intent'] == 'plan'
        assert body['care_plan_guid'] == body['guid']

    def test_create_inherits_goals_from_plandef(self, client):
        with _patch_plandef():
            r = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-1',
                'plan_definition_guid': 'pd-1',
            })
        body = r.get_json()
        assert body['goals']
        assert body['goals'][0]['concept_guid'] == 'c-1'

    def test_create_overrides_goals(self, client):
        custom = [{'concept_guid': 'c-x', 'target_value': 6.5,
                   'target_comparator': '<', 'description': 'Tighter'}]
        with _patch_plandef():
            r = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-2',
                'plan_definition_guid': 'pd-1',
                'goals': custom,
            })
        body = r.get_json()
        assert body['goals'] == custom

    def test_missing_required_fields(self, client):
        r = client.post('/api/v1/careplans', json={'patient_guid': 'pat-1'})
        assert r.status_code == 400

    def test_create_when_plandef_unreachable(self, client):
        """If plan.pdhc is down, CarePlan is still created but
        snapshot is empty. Clinician can re-fetch later."""
        with patch('app.api.care_plans.plan_definition_service.get_plan_definition',
                   side_effect=Exception('plan unreachable')):
            r = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-3',
                'plan_definition_guid': 'pd-down',
            })
        assert r.status_code == 201
        body = r.get_json()
        assert body['plan_definition_snapshot'] is None


class TestReadCarePlan:

    def test_read_404(self, client):
        r = client.get('/api/v1/careplans/no-such-guid')
        assert r.status_code == 404

    def test_create_then_read(self, client):
        with _patch_plandef():
            cr = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-r', 'plan_definition_guid': 'pd-1',
            })
        guid = cr.get_json()['guid']
        r = client.get(f'/api/v1/careplans/{guid}')
        assert r.status_code == 200
        assert r.get_json()['guid'] == guid


class TestListByPatient:

    def test_list_filters_by_patient(self, client):
        with _patch_plandef():
            client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-list-A', 'plan_definition_guid': 'pd-1'})
            client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-list-A', 'plan_definition_guid': 'pd-1',
                'title': 'second plan'})
            client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-list-B', 'plan_definition_guid': 'pd-1'})
        r = client.get('/api/v1/careplans?patient_guid=pat-list-A')
        body = r.get_json()
        assert body['total'] == 2

    def test_list_filters_by_status(self, client):
        with _patch_plandef():
            client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-status', 'plan_definition_guid': 'pd-1',
                'status': 'active'})
            client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-status', 'plan_definition_guid': 'pd-1',
                'status': 'completed'})
        r = client.get('/api/v1/careplans?patient_guid=pat-status&status=active')
        body = r.get_json()
        assert body['total'] == 1
        assert body['careplans'][0]['status'] == 'active'


class TestUpdate:

    def test_update_status_and_goals(self, client):
        with _patch_plandef():
            cr = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-u', 'plan_definition_guid': 'pd-1'})
        guid = cr.get_json()['guid']
        r = client.put(f'/api/v1/careplans/{guid}', json={
            'status': 'active',
            'goals': [{'concept_guid': 'new-c', 'target_value': 5.5,
                       'target_comparator': '<'}],
        })
        body = r.get_json()
        assert body['status'] == 'active'
        assert body['goals'][0]['concept_guid'] == 'new-c'

    def test_update_404(self, client):
        r = client.put('/api/v1/careplans/no-such-guid', json={'status': 'x'})
        assert r.status_code == 404


class TestContext:

    def test_context_returns_chain(self, client):
        with _patch_plandef():
            cr = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-ctx', 'plan_definition_guid': 'pd-1'})
        guid = cr.get_json()['guid']
        r = client.get(f'/api/v1/careplans/{guid}/context')
        assert r.status_code == 200
        body = r.get_json()
        assert body['care_plan_guid'] == guid
        assert body['plan_definition_guid'] == 'pd-1'
        assert body['transactions']
        assert body['transactions'][0]['transaction_guid'] == 'tx-1'
        assert body['transactions'][0]['concept_guid'] == 'c-hba1c'


class TestServiceRequestCarePlanGuidColumn:
    """The migration also adds service_requests.care_plan_guid. Verify
    the column exists and accepts NULL (legacy SRs) or a guid (new
    SRs derived from a CarePlan)."""

    def test_service_request_care_plan_guid_nullable(self, app):
        from app.models.service_request_models import ServiceRequest
        with app.app_context():
            sr = ServiceRequest(
                patient_guid='pat-sr',
                plan_definition_guid='pd-1',
                requester_user_guid='user-1',
            )
            db.session.add(sr)
            db.session.commit()
            assert sr.care_plan_guid is None  # legacy SR — no CarePlan

    def test_service_request_links_to_careplan(self, app, client):
        from app.models.service_request_models import ServiceRequest
        with _patch_plandef():
            cr = client.post('/api/v1/careplans', json={
                'patient_guid': 'pat-link', 'plan_definition_guid': 'pd-1'})
        cp_guid = cr.get_json()['guid']
        with app.app_context():
            sr = ServiceRequest(
                patient_guid='pat-link',
                plan_definition_guid='pd-1',
                requester_user_guid='user-1',
                care_plan_guid=cp_guid,
            )
            db.session.add(sr)
            db.session.commit()
            assert sr.care_plan_guid == cp_guid
