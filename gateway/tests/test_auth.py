"""Tests for authentication and SSO integration (Steps 5.e–5.f)."""
import pytest


def test_auth_me_dev_mode(client):
    """In AUTH_DISABLED mode, /me returns dev access blob."""
    resp = client.get('/api/v1/auth/me')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get('user_guid') or data.get('is_su_admin')


def test_auth_login_redirect_disabled(client):
    """In AUTH_DISABLED mode, login redirects to dashboard."""
    resp = client.get('/api/v1/auth/login', follow_redirects=False)
    assert resp.status_code == 302


def test_protected_endpoint_accessible_in_dev(client):
    """In AUTH_DISABLED mode, protected endpoints are accessible."""
    resp = client.get('/api/v1/Patient')
    # Should get a response (even if upstream fails), not 401
    assert resp.status_code != 401
