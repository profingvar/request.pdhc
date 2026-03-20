"""Comprehensive API endpoint test script (Rules 9, 20 — Steps 14.a–14.c).
Exercises every API endpoint per the capability statement."""
import pytest


class TestAuthEndpoints:
    def test_login_redirect(self, client):
        resp = client.get('/api/v1/auth/login', follow_redirects=False)
        assert resp.status_code == 302

    def test_me(self, client):
        resp = client.get('/api/v1/auth/me')
        assert resp.status_code == 200

    def test_logout(self, client):
        resp = client.post('/api/v1/auth/logout')
        assert resp.status_code == 200


class TestPatientEndpoints:
    def test_list(self, client):
        resp = client.get('/api/v1/Patient')
        assert resp.status_code in (200, 502)

    def test_read(self, client):
        resp = client.get('/api/v1/Patient/test-guid')
        assert resp.status_code in (200, 404, 502)

    def test_create_no_body(self, client):
        resp = client.post('/api/v1/Patient')
        assert resp.status_code == 400

    def test_create_with_body(self, client):
        resp = client.post('/api/v1/Patient', json={'resourceType': 'Patient', 'name': [{'family': 'Test'}]})
        assert resp.status_code in (200, 201, 502)

    def test_update_no_body(self, client):
        resp = client.put('/api/v1/Patient/test-guid')
        assert resp.status_code == 400

    def test_delete(self, client):
        resp = client.delete('/api/v1/Patient/test-guid')
        assert resp.status_code in (200, 404, 502)


class TestCarePlanEndpoints:
    def test_list(self, client):
        resp = client.get('/api/v1/CarePlan')
        assert resp.status_code in (200, 502)

    def test_read(self, client):
        resp = client.get('/api/v1/CarePlan/test-guid')
        assert resp.status_code in (200, 404, 502)


class TestExportEndpoints:
    def test_preview(self, client):
        resp = client.get('/api/v1/CarePlan/test-guid/export/preview')
        assert resp.status_code in (200, 404, 502)

    def test_csv_export(self, client):
        resp = client.post('/api/v1/CarePlan/test-guid/export/csv')
        assert resp.status_code in (200, 404, 422, 502)


class TestDispatchEndpoints:
    def test_submit_no_body(self, client):
        resp = client.post('/api/v1/CarePlan/test-guid/dispatch')
        assert resp.status_code == 400

    def test_submit_missing_provider(self, client):
        resp = client.post('/api/v1/CarePlan/test-guid/dispatch', json={'notes': 'test'})
        assert resp.status_code == 400

    def test_status_not_found(self, client):
        resp = client.get('/api/v1/CarePlan/test-guid/dispatch/bad-token')
        assert resp.status_code == 404


class TestProviderEndpoints:
    def test_list(self, client):
        resp = client.get('/api/v1/providers')
        assert resp.status_code in (200, 502)


class TestCapabilityStatement:
    def test_metadata(self, client):
        resp = client.get('/api/v1/metadata')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['resourceType'] == 'CapabilityStatement'
        assert data['fhirVersion'] == '5.0.0'

    def test_health(self, client):
        resp = client.get('/api/health')
        assert resp.status_code == 200
