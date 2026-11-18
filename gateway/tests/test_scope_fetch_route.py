"""fetch_scope must call a route contract.pdhc.se actually serves.

It called /internal/contract/<g>/scope, which the reverse proxy sends to the
frontend: 200 HTML, parsed as "unreachable", fail-open on every request.
Found on the cgm_provider onboarding, 2026-11-18.
"""
import logging

from app.services import scope_service


class _Resp:
    def __init__(self, status, payload=None, ctype="application/json"):
        self.status_code = status
        self._p = payload
        self.headers = {"content-type": ctype}

    def json(self):
        if self._p is None:
            raise ValueError("not json")
        return self._p


def _capture(monkeypatch, resp):
    seen = {}

    def fake_get(url, headers=None, timeout=None, **kw):
        seen["url"] = url
        seen["headers"] = headers or {}
        return resp
    monkeypatch.setattr(scope_service.requests, "get", fake_get)
    return seen


def test_it_calls_the_routed_public_scope_endpoint(app, monkeypatch):
    app.config["CONTRACT_BASE_URL"] = "https://contract.test"
    seen = _capture(monkeypatch, _Resp(200, {"status": "executed",
                                             "scope_defined": True,
                                             "request_scope": ["c1"]}))
    with app.app_context():
        out = scope_service.fetch_scope("g-1")
    assert seen["url"] == "https://contract.test/fhir/Contract/g-1/scope"
    assert "/internal/" not in seen["url"]
    assert out["request_scope"] == ["c1"]


def test_it_needs_no_service_key(app, monkeypatch):
    app.config["CONTRACT_BASE_URL"] = "https://contract.test"
    app.config["INTERNAL_SERVICE_KEY"] = ""
    _capture(monkeypatch, _Resp(200, {"status": "executed"}))
    with app.app_context():
        assert scope_service.fetch_scope("g-1") == {"status": "executed"}


def test_a_non_json_200_is_logged_as_an_error(app, monkeypatch, caplog):
    app.config["CONTRACT_BASE_URL"] = "https://contract.test"
    _capture(monkeypatch, _Resp(200, None, "text/html"))
    with app.app_context(), caplog.at_level(logging.ERROR):
        assert scope_service.fetch_scope("g-1") is None
    assert any("non-JSON" in r.message for r in caplog.records)
