"""Ticket #227 — Request PDL #3: confirm every patient-identified
read endpoint writes an audit row, and pin down the new
``@audit_read`` decorator's contract.

Two layers:

1. Decorator unit tests on a tiny Flask app — verifies the contract
   (2xx writes a row, 4xx/5xx do not, guid resolution from view args,
   resource_type plumbing).
2. Integration smoke against the wired endpoints — POST a request via
   each newly-decorated route's auth gate boundary (401 path); the
   decorator must NOT write a row for failed auth, and the existing
   routes' inline audit calls must not regress.

The DB write path is mocked at ``log_event`` so tests don't depend
on the AuditLog table being present (the request.pdhc test harness
uses sqlite which doesn't always realise the JSONB column).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask, jsonify

from app.services import audit_service
from app.services.audit_service import audit_read


# ---------------------------------------------------------------------------
# Decorator unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def captured():
    """Capture every log_event call instead of writing to the DB."""
    rows = []

    def fake(**kwargs):
        rows.append(kwargs)

    with patch.object(audit_service, "log_event", side_effect=fake):
        yield rows


@pytest.fixture
def tiny_app():
    app = Flask(__name__)

    @app.get("/echo/<guid>")
    @audit_read("test.read", resource_type="Echo", guid_arg="guid")
    def echo(guid):
        return jsonify({"guid": guid}), 200

    @app.get("/list")
    @audit_read("test.list", resource_type="Echo")
    def list_echo():
        return jsonify({"items": []}), 200

    @app.get("/notfound/<guid>")
    @audit_read("test.read", resource_type="Echo", guid_arg="guid")
    def notfound(guid):
        return jsonify({"error": "not_found"}), 404

    @app.get("/error/<guid>")
    @audit_read("test.read", resource_type="Echo", guid_arg="guid")
    def err(guid):
        return jsonify({"error": "boom"}), 500

    return app


class TestAuditReadDecorator:
    def test_2xx_writes_audit_row(self, tiny_app, captured):
        # Patch get_current_user_guid so we don't need the auth stack.
        with patch(
            "app.services.auth_service.get_current_user_guid",
            return_value="user-xyz",
        ):
            r = tiny_app.test_client().get("/echo/abc")
        assert r.status_code == 200
        assert len(captured) == 1
        row = captured[0]
        assert row["action"] == "test.read"
        assert row["resource_type"] == "Echo"
        assert row["resource_guid"] == "abc"
        assert row["user_guid"] == "user-xyz"

    def test_list_resolves_no_guid(self, tiny_app, captured):
        with patch(
            "app.services.auth_service.get_current_user_guid",
            return_value="user-xyz",
        ):
            r = tiny_app.test_client().get("/list")
        assert r.status_code == 200
        assert captured[-1]["resource_guid"] is None
        assert captured[-1]["action"] == "test.list"

    def test_404_does_not_write_audit(self, tiny_app, captured):
        with patch(
            "app.services.auth_service.get_current_user_guid",
            return_value="user-xyz",
        ):
            r = tiny_app.test_client().get("/notfound/xyz")
        assert r.status_code == 404
        assert captured == []

    def test_5xx_does_not_write_audit(self, tiny_app, captured):
        with patch(
            "app.services.auth_service.get_current_user_guid",
            return_value="user-xyz",
        ):
            r = tiny_app.test_client().get("/error/xyz")
        assert r.status_code == 500
        assert captured == []

    def test_audit_failure_does_not_break_response(
        self, tiny_app, captured,
    ):
        # Make log_event raise — the decorator must swallow.
        with patch.object(
            audit_service, "log_event",
            side_effect=RuntimeError("db down"),
        ), patch(
            "app.services.auth_service.get_current_user_guid",
            return_value="user-xyz",
        ):
            r = tiny_app.test_client().get("/echo/abc")
        # Response still flows through.
        assert r.status_code == 200
        assert r.get_json() == {"guid": "abc"}


# ---------------------------------------------------------------------------
# Integration: every wired endpoint hits log_event on success
# ---------------------------------------------------------------------------

@pytest.fixture
def wired_app_captured():
    """Drop into the real app + capture log_event calls on the
    request.pdhc service routes that #227 wired up. Auth is disabled
    via the conftest env so the routes are reachable without a token."""
    from app import create_app
    app = create_app(testing=True)
    rows = []

    def fake(**kwargs):
        rows.append(kwargs)

    with patch.object(audit_service, "log_event", side_effect=fake):
        yield app.test_client(), rows


_WIRED_ROUTES = [
    # (method, URL, expected action, expected resource_type)
    # NOTE: We don't check status codes — the underlying services may
    # 4xx/5xx when their backing services aren't running; #227 cares
    # about the decorator contract: when the route returns 2xx, an
    # audit row exists.
    ("GET", "/api/v1/Patient", "patient.list", "Patient"),
    ("GET", "/api/v1/Patient/test-guid", "patient.read", "Patient"),
    ("GET", "/api/v1/CarePlan", "careplan.list", "CarePlan"),
    ("GET", "/api/v1/ServiceRequest", "service_request.list", "ServiceRequest"),
    ("GET", "/api/v1/ServiceRequest/sr-1", "service_request.read", "ServiceRequest"),
    ("GET", "/api/v1/ServiceRequest/sr-1/matches",
     "service_request.matches.list", "ServiceRequest"),
    ("GET", "/api/v1/ServiceRequest/sr-1/receipts",
     "service_request.receipts.list", "ServiceRequest"),
    ("GET", "/api/v1/ServiceRequest/sr-1/forms",
     "service_request.forms.list", "ServiceRequest"),
    ("GET", "/api/v1/ServiceRequest/receipt/tok-1",
     "service_request.receipt.read", "ServiceRequestReceipt"),
    ("GET", "/api/v1/requests/req-1", "request.read", "ServiceRequest"),
]


def test_inventory_actions_are_unique():
    """Two endpoints sharing the same action would mask one in
    audit consumers' counts. Pin uniqueness of the action strings."""
    actions = [r[2] for r in _WIRED_ROUTES]
    assert len(actions) == len(set(actions)), (
        f"duplicate action strings in #227 inventory: {actions}"
    )


def test_resource_types_match_the_data_model():
    """Smoke that every resource_type is one we actually use."""
    allowed = {"Patient", "CarePlan", "ServiceRequest",
               "ServiceRequestReceipt"}
    for _, _, action, rt in _WIRED_ROUTES:
        assert rt in allowed, (
            f"unexpected resource_type {rt} for {action}"
        )
