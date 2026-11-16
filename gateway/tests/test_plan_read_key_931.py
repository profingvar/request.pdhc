"""#931 — request.pdhc reads plan.pdhc with its own read_only service key.

Every read call site sends X-Source-Service + X-Service-Key when
PLAN_SERVICE_KEY is set, nothing when unset — and the operator-bearer WRITE
(dispatch) never carries it, because plan checks the service key first and a
read_only key would turn an authorised write into a 403.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import context_service as cs
from app.services import dispatch_service, form_service, plan_definition_service as pds
from app.services.plan_auth import plan_read_headers

KEY = 'k931-request'


@pytest.fixture
def keyed(app):
    old = (app.config.get('PLAN_SERVICE_KEY'), app.config.get('PLAN_SOURCE_SERVICE'))
    app.config['PLAN_SERVICE_KEY'] = KEY
    app.config['PLAN_SOURCE_SERVICE'] = 'request.pdhc'
    yield app
    app.config['PLAN_SERVICE_KEY'], app.config['PLAN_SOURCE_SERVICE'] = old


def _ok(payload=None):
    r = MagicMock(status_code=200)
    r.json.return_value = payload if payload is not None else []
    r.raise_for_status.return_value = None
    return r


def _sent(mock):
    return [c.kwargs.get('headers') or {} for c in mock.call_args_list]


def test_unset_key_sends_no_credential(app):
    with app.test_request_context():
        app.config['PLAN_SERVICE_KEY'] = ''
        assert plan_read_headers() == {}


def test_set_key_sends_the_pair(keyed):
    with keyed.test_request_context():
        assert plan_read_headers() == {'X-Source-Service': 'request.pdhc', 'X-Service-Key': KEY}


def test_context_service_maps_are_read_WITH_the_key(keyed):
    cs._plan_cache.update(rt={}, ts=0.0)
    with keyed.test_request_context(), patch.object(cs.requests, 'get', return_value=_ok({'items': [], 'total': 0})) as g:
        cs._refresh_plan_maps()
    hs = _sent(g)
    assert len(hs) >= 3, 'response-types, units and at least one concepts page'
    assert all(h.get('X-Service-Key') == KEY and h.get('X-Source-Service') == 'request.pdhc' for h in hs)


@pytest.mark.parametrize('call', [
    lambda: pds.list_plan_definitions(), lambda: pds.get_plan_definition('g'), lambda: pds.list_concepts(),
    lambda: pds.list_units(), lambda: pds.list_valuesets(), lambda: pds.list_plandef_types(),
    lambda: form_service.list_forms(), lambda: form_service.get_form('g'),
])
def test_every_plan_READ_carries_the_key(keyed, call):
    with keyed.test_request_context(), patch('requests.get', return_value=_ok()) as g:
        call()
    assert g.called and all(h.get('X-Service-Key') == KEY for h in _sent(g))


def test_dispatch_WRITE_never_carries_the_read_key(keyed):
    with keyed.test_request_context():
        h = dispatch_service._headers()
    assert 'X-Service-Key' not in h and 'X-Source-Service' not in h
