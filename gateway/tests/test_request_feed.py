"""Tests for the provider subscription request feed (new endpoints).

Tests cover:
- GET /api/v1/requests (list by provider_guid)
- GET /api/v1/requests/<guid> (single request)
- PUT /api/v1/requests/<guid>/status (provider status callback)
- X-API-Key authentication
"""
import pytest
import uuid
from app import db
from app.models.dispatch_models import DispatchRequest, DispatchReceipt


@pytest.fixture
def sample_dispatch(app):
    """Create a sample dispatch request + receipt in the DB."""
    with app.app_context():
        dr = DispatchRequest(
            guid=str(uuid.uuid4()),
            plan_definition_guid='cp-test-001',
            provider_guid='provider-aaa-111',
            dispatch_notes='Test dispatch',
            status='submitted',
            idempotency_key=str(uuid.uuid4()),
        )
        db.session.add(dr)
        db.session.flush()

        receipt = DispatchReceipt(
            dispatch_request_guid=dr.guid,
            receipt_token=str(uuid.uuid4()),
            status='accepted',
        )
        db.session.add(receipt)
        db.session.commit()
        return dr.guid, dr.provider_guid, receipt.receipt_token


@pytest.fixture
def multiple_dispatches(app):
    """Create dispatches for two different providers."""
    with app.app_context():
        guids = []
        for i, prov in enumerate(['provider-aaa-111', 'provider-aaa-111', 'provider-bbb-222']):
            dr = DispatchRequest(
                guid=str(uuid.uuid4()),
                plan_definition_guid=f'cp-multi-{i}',
                provider_guid=prov,
                status='submitted',
                idempotency_key=str(uuid.uuid4()),
            )
            db.session.add(dr)
            db.session.flush()
            receipt = DispatchReceipt(
                dispatch_request_guid=dr.guid,
                receipt_token=str(uuid.uuid4()),
                status='accepted',
            )
            db.session.add(receipt)
            guids.append((dr.guid, prov))
        db.session.commit()
        return guids


# --- GET /api/v1/requests ---

class TestListRequests:
    def test_requires_provider_guid(self, client):
        """Must supply provider_guid."""
        resp = client.get('/api/v1/requests')
        assert resp.status_code == 400
        assert 'provider_guid' in resp.get_json()['message']

    def test_returns_empty_for_unknown_provider(self, client):
        """Unknown provider returns empty list, not error."""
        resp = client.get('/api/v1/requests?provider_guid=nonexistent')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['requests'] == []
        assert data['has_more'] is False

    def test_returns_dispatches_for_provider(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.get(f'/api/v1/requests?provider_guid={prov_guid}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data['requests']) == 1
        assert data['requests'][0]['request_guid'] == dr_guid
        assert data['requests'][0]['provider_guid'] == prov_guid

    def test_filters_by_provider(self, client, multiple_dispatches):
        """Only returns requests for the specified provider."""
        resp_a = client.get('/api/v1/requests?provider_guid=provider-aaa-111')
        resp_b = client.get('/api/v1/requests?provider_guid=provider-bbb-222')
        data_a = resp_a.get_json()
        data_b = resp_b.get_json()
        # provider-aaa-111 has at least 2, provider-bbb-222 has at least 1
        assert len(data_a['requests']) >= 2
        assert len(data_b['requests']) >= 1
        for r in data_a['requests']:
            assert r['provider_guid'] == 'provider-aaa-111'
        for r in data_b['requests']:
            assert r['provider_guid'] == 'provider-bbb-222'

    def test_response_has_careplan_structure(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.get(f'/api/v1/requests?provider_guid={prov_guid}')
        entry = resp.get_json()['requests'][0]
        assert 'careplan' in entry
        assert 'careplan_guid' in entry['careplan']
        assert 'patient' in entry['careplan']
        assert 'activities' in entry['careplan']
        assert 'dispatch_metadata' in entry['careplan']

    def test_response_has_receipt_token(self, client, sample_dispatch):
        dr_guid, prov_guid, receipt_token = sample_dispatch
        resp = client.get(f'/api/v1/requests/{dr_guid}')
        assert resp.status_code == 200
        entry = resp.get_json()
        assert entry['receipt_token'] == receipt_token

    def test_has_more_and_cursor(self, client, app):
        """Pagination: cursor and has_more work correctly."""
        with app.app_context():
            for i in range(5):
                dr = DispatchRequest(
                    plan_definition_guid=f'cp-page-{i}',
                    provider_guid='provider-pager',
                    status='submitted',
                    idempotency_key=str(uuid.uuid4()),
                )
                db.session.add(dr)
                db.session.flush()
                db.session.add(DispatchReceipt(
                    dispatch_request_guid=dr.guid,
                    status='accepted',
                ))
            db.session.commit()

        resp = client.get('/api/v1/requests?provider_guid=provider-pager&_count=3')
        data = resp.get_json()
        assert len(data['requests']) == 3
        assert data['has_more'] is True
        assert data['cursor'] is not None

        # Fetch next page
        resp2 = client.get(f'/api/v1/requests?provider_guid=provider-pager&_count=3&cursor={data["cursor"]}')
        data2 = resp2.get_json()
        assert len(data2['requests']) == 2
        assert data2['has_more'] is False


# --- GET /api/v1/requests/<guid> ---

class TestGetSingleRequest:
    def test_get_existing(self, client, sample_dispatch):
        dr_guid, _, _ = sample_dispatch
        resp = client.get(f'/api/v1/requests/{dr_guid}')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['request_guid'] == dr_guid

    def test_get_not_found(self, client):
        resp = client.get('/api/v1/requests/nonexistent-guid')
        assert resp.status_code == 404


# --- PUT /api/v1/requests/<guid>/status ---

class TestUpdateRequestStatus:
    def test_update_status(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status', json={
            'provider_guid': prov_guid,
            'status': 'acknowledged',
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['provider_status'] == 'acknowledged'

    def test_update_to_completed(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status', json={
            'provider_guid': prov_guid,
            'status': 'completed',
        })
        assert resp.status_code == 200
        assert resp.get_json()['provider_status'] == 'completed'

    def test_invalid_status(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status', json={
            'provider_guid': prov_guid,
            'status': 'bogus',
        })
        assert resp.status_code == 400

    def test_wrong_provider_guid(self, client, sample_dispatch):
        dr_guid, _, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status', json={
            'provider_guid': 'wrong-provider',
            'status': 'acknowledged',
        })
        assert resp.status_code == 403

    def test_not_found(self, client):
        resp = client.put('/api/v1/requests/nonexistent/status', json={
            'provider_guid': 'any',
            'status': 'acknowledged',
        })
        assert resp.status_code == 404

    def test_no_body(self, client, sample_dispatch):
        dr_guid, _, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status')
        assert resp.status_code == 400

    def test_missing_fields(self, client, sample_dispatch):
        dr_guid, _, _ = sample_dispatch
        resp = client.put(f'/api/v1/requests/{dr_guid}/status', json={
            'provider_guid': 'x',
        })
        assert resp.status_code == 400


# --- X-API-Key auth ---

class TestApiKeyAuth:
    def test_api_key_accepted_on_requests(self, client):
        """X-API-Key header is accepted for /api/v1/requests."""
        resp = client.get(
            '/api/v1/requests?provider_guid=test',
            headers={'X-API-Key': 'test-key-123'},
        )
        assert resp.status_code == 200

    def test_api_key_accepted_on_status_update(self, client, sample_dispatch):
        dr_guid, prov_guid, _ = sample_dispatch
        resp = client.put(
            f'/api/v1/requests/{dr_guid}/status',
            headers={'X-API-Key': 'test-key-123'},
            json={'provider_guid': prov_guid, 'status': 'acknowledged'},
        )
        assert resp.status_code == 200
