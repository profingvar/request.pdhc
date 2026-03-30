"""Proxy service for the Plan catalogue's form/questionnaire endpoints."""

import requests
from flask import current_app


def _headers():
    h = {'Accept': 'application/json'}
    key = current_app.config.get('PLAN_API_KEY')
    if key:
        h['X-API-Key'] = key
    return h


def _base(path=''):
    base = current_app.config['PLAN_BASE_URL'].rstrip('/')
    return f"{base}/api/v1{path}"


def list_forms(params=None):
    """List the form catalogue from Plan backend."""
    default_params = {'per_page': '200'}
    if params:
        default_params.update(params)
    try:
        resp = requests.get(_base('/forms'), headers=_headers(),
                            params=default_params, timeout=15)
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_form(guid):
    """Get a single form definition (latest version) from Plan backend."""
    try:
        resp = requests.get(_base(f'/forms/{guid}'), headers=_headers(), timeout=15)
        if resp.status_code == 404:
            return {'code': 'not_found', 'message': f'Form {guid} not found'}, 404
        resp.raise_for_status()
        return resp.json(), resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502


def get_questionnaire(form_guid):
    """Produce/retrieve the FHIR Questionnaire JSON for a form.

    Tries the form-definitions questionnaire endpoint first,
    falls back to the forms/produce endpoint.
    """
    # Primary: forms catalogue questionnaire endpoint (API key auth)
    try:
        resp = requests.get(
            _base(f'/forms/{form_guid}/questionnaire'),
            headers=_headers(), timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), 200
    except requests.RequestException:
        pass

    # Fallback: form-definitions endpoint
    try:
        resp = requests.get(
            _base(f'/form-definitions/{form_guid}/questionnaire'),
            headers=_headers(), timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), 200
    except requests.RequestException:
        pass

    return {'code': 'upstream_error', 'message': 'Could not produce Questionnaire'}, 502


def get_render_ready(form_guid):
    """Get the render-ready JSON payload for a form."""
    # Primary: forms catalogue render-ready endpoint
    try:
        resp = requests.get(
            _base(f'/forms/{form_guid}/render-ready'),
            headers=_headers(), timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), 200
    except requests.RequestException:
        pass

    # Fallback: form-definitions endpoint
    try:
        resp = requests.get(
            _base(f'/form-definitions/{form_guid}/render-ready'),
            headers=_headers(), timeout=15,
        )
        if resp.status_code == 200:
            return resp.json(), 200
        return {'code': 'upstream_error', 'message': f'Status {resp.status_code}'}, resp.status_code
    except requests.RequestException as e:
        return {'code': 'upstream_error', 'message': str(e)}, 502
