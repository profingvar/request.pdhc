"""Tests for application factory and configuration (Steps 3.h–3.i)."""
import pytest


def test_app_creates(app):
    """App factory creates without error."""
    assert app is not None


def test_app_testing_config(app):
    """Testing config is applied."""
    assert app.config['TESTING'] is True


def test_config_upstream_urls(app):
    """Upstream service URLs are loaded from config."""
    assert app.config['IPS_BASE_URL']
    assert app.config['PLAN_BASE_URL']
    assert app.config['SSO_BASE_URL']


def test_config_database_url(app):
    """Database URL is present."""
    assert 'request_pdhc' in app.config['SQLALCHEMY_DATABASE_URI']


def test_health_endpoint(client):
    """Health endpoint returns 200."""
    resp = client.get('/api/health')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'


def test_404_api_returns_json(client):
    """API 404 returns JSON error."""
    resp = client.get('/api/v1/nonexistent')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data['code'] == 'not_found'
