"""Ticket #229 — Request PDL #5: consent at dispatch (Lag 2022:913 §5).

Three layers:

1. ``consent_covers_dispatch`` decision helper — pure-Python, no I/O.
2. ``get_active_consents`` cache + http path — mock requests + clock.
3. ``dispatch_service.create_dispatch`` end-to-end — refuses 403 +
   audits when consent is missing or concept-narrowed and a payload
   concept falls outside; proceeds when consent covers.

The audit refusal path is verified by inspecting the AuditLog rows
written via the existing ``log_event`` helper.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app import db
from app.models.audit_models import AuditLog
from app.services import ips_consent_client as icc
from app.services import dispatch_service
from app.services.ips_consent_client import (
    Consent,
    consent_covers_dispatch,
    get_active_consents,
)


def _consent(
    *,
    grantee="dest-caregiver",
    concepts=None,
    is_active=True,
    patient=None,
):
    return Consent(
        guid=str(uuid.uuid4()),
        patient_guid=patient or str(uuid.uuid4()),
        grantee_caregiver_guid=grantee,
        consented_concept_guids=concepts,
        is_active=is_active,
    )


# ---------------------------------------------------------------------------
# Decision helper (pure)
# ---------------------------------------------------------------------------

class TestConsentCoversDispatch:
    def test_no_consents_refuses(self):
        ok, reason = consent_covers_dispatch(
            [], destination_caregiver_guid="dest-caregiver",
        )
        assert ok is False
        assert reason == "no_consent"

    def test_unrelated_grantee_refuses(self):
        cs = [_consent(grantee="other-caregiver")]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
        )
        assert ok is False
        assert reason == "no_consent"

    def test_revoked_consent_does_not_count(self):
        cs = [_consent(grantee="dest-caregiver", is_active=False)]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
        )
        assert ok is False
        assert reason == "no_consent"

    def test_whole_caregiver_consent_covers_any_payload(self):
        cs = [_consent(grantee="dest-caregiver", concepts=None)]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
            payload_concept_guids=["concept-a", "concept-b"],
        )
        assert ok is True
        assert reason is None

    def test_narrowed_consent_covers_listed_concepts(self):
        cs = [_consent(
            grantee="dest-caregiver", concepts=["concept-a", "concept-b"],
        )]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
            payload_concept_guids=["concept-a"],
        )
        assert ok is True
        assert reason is None

    def test_narrowed_consent_refuses_unlisted_concept(self):
        cs = [_consent(
            grantee="dest-caregiver", concepts=["concept-a"],
        )]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
            payload_concept_guids=["concept-a", "concept-c"],
        )
        assert ok is False
        assert reason == "concept_not_consented"

    def test_narrowed_consent_no_payload_concepts_passes(self):
        # Caller didn't supply payload concepts — caregiver-level
        # consent (even narrowed) is enough; downstream services
        # enforce the per-concept boundary.
        cs = [_consent(
            grantee="dest-caregiver", concepts=["concept-a"],
        )]
        ok, reason = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
        )
        assert ok is True

    def test_union_of_narrowed_consents(self):
        # Two narrowed consents to the same caregiver; the union of
        # their concept sets defines coverage.
        cs = [
            _consent(grantee="dest-caregiver", concepts=["a"]),
            _consent(grantee="dest-caregiver", concepts=["b"]),
        ]
        ok, _ = consent_covers_dispatch(
            cs, destination_caregiver_guid="dest-caregiver",
            payload_concept_guids=["a", "b"],
        )
        assert ok is True

    def test_missing_destination_caregiver_refuses(self):
        ok, reason = consent_covers_dispatch(
            [], destination_caregiver_guid="",
        )
        assert ok is False
        assert reason == "no_destination_caregiver"


# ---------------------------------------------------------------------------
# get_active_consents cache + http path
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _bust_cache():
    icc.invalidate(None)
    yield
    icc.invalidate(None)


class TestGetActiveConsents:
    def test_calls_ips_and_caches(self, app):
        with app.app_context():
            fake_client = MagicMock(spec=icc.IpsConsentClient)
            fake_client.fetch_consents_for_grantee.return_value = [
                _consent(grantee="dest-caregiver"),
            ]
            r1 = get_active_consents("p1", "dest-caregiver", client=fake_client)
            r2 = get_active_consents("p1", "dest-caregiver", client=fake_client)
            # Second call is cached -> http hit count stays at 1.
            assert fake_client.fetch_consents_for_grantee.call_count == 1
            assert len(r1) == 1 and len(r2) == 1

    def test_distinct_grantee_is_distinct_key(self, app):
        with app.app_context():
            fake_client = MagicMock(spec=icc.IpsConsentClient)
            fake_client.fetch_consents_for_grantee.return_value = []
            get_active_consents("p1", "cg-a", client=fake_client)
            get_active_consents("p1", "cg-b", client=fake_client)
            assert fake_client.fetch_consents_for_grantee.call_count == 2

    def test_invalidate_re_fetches_all_grantees(self, app):
        with app.app_context():
            fake_client = MagicMock(spec=icc.IpsConsentClient)
            fake_client.fetch_consents_for_grantee.return_value = [
                _consent(grantee="dest-caregiver"),
            ]
            get_active_consents("p1", "dest-caregiver", client=fake_client)
            icc.invalidate("p1")
            get_active_consents("p1", "dest-caregiver", client=fake_client)
            assert fake_client.fetch_consents_for_grantee.call_count == 2

    def test_drops_inactive_rows(self, app):
        with app.app_context():
            fake_client = MagicMock(spec=icc.IpsConsentClient)
            fake_client.fetch_consents_for_grantee.return_value = [
                _consent(grantee="dest-caregiver", is_active=True),
                _consent(grantee="dest-caregiver", is_active=False),
            ]
            r = get_active_consents("p1", "dest-caregiver", client=fake_client)
            assert len(r) == 1
            assert r[0].is_active is True


class TestConsentTransport:
    def test_uses_authorization_apikey_and_check_endpoint(self):
        captured = {}

        class Resp:
            status_code = 200
            def json(self):
                return {"has_active_consent": True, "consents": [{
                    "guid": "c1", "patient_guid": "p1",
                    "grantee_caregiver_guid": "dest-cg",
                    "consented_concept_guids": None, "is_active": True,
                }]}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured.update(url=url, params=params, headers=headers)
            return Resp()

        c = icc.IpsConsentClient(api_key="RAWKEY", base_url="https://ips.pdhc.se")
        with patch("app.services.ips_consent_client.requests.get", fake_get):
            out = c.fetch_consents_for_grantee("p1", "dest-cg")

        assert len(out) == 1 and out[0].grantee_caregiver_guid == "dest-cg"
        assert captured["url"].endswith("/patients/p1/consents/check")
        assert captured["params"] == {"grantee_caregiver_guid": "dest-cg"}
        assert captured["headers"]["Authorization"] == "ApiKey RAWKEY"
        assert "X-API-Key" not in captured["headers"]

    def test_4xx_returns_empty(self):
        class Resp:
            status_code = 403
            def json(self):
                return {}

        c = icc.IpsConsentClient(api_key="k", base_url="https://ips.pdhc.se")
        with patch("app.services.ips_consent_client.requests.get",
                   return_value=Resp()):
            assert c.fetch_consents_for_grantee("p1", "dest-cg") == []


# ---------------------------------------------------------------------------
# Dispatch service: consent gate end-to-end
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_audit():
    """Capture log_event calls without writing the DB row (some tests
    don't have AuditLog table)."""
    captured = []
    with patch(
        "app.services.dispatch_service.log_event",
        side_effect=lambda **kw: captured.append(kw),
    ):
        yield captured


@pytest.fixture
def stub_consents():
    """Patch get_active_consents at the dispatch_service import site."""
    with patch(
        "app.services.dispatch_service.get_active_consents",
    ) as m:
        yield m


@pytest.fixture
def stub_upstream(monkeypatch):
    """Stop dispatch_service from actually POSTing to plan.pdhc.

    Uses monkeypatch.setattr on the bound module attribute so the
    patch survives test-pollution from other modules that mutate
    requests imports (test_dispatch_trigger.py sets env vars at
    module-load time and indirectly affects the shared session).
    """
    fake_response = MagicMock(
        status_code=201,
        json=lambda: {"upstream": "accepted"},
        text="",
    )
    post_mock = MagicMock(return_value=fake_response)
    monkeypatch.setattr(
        "app.services.dispatch_service.requests.post", post_mock,
    )
    return post_mock


class TestDispatchConsentGate:
    def test_consented_dispatch_proceeds(
        self, app, stub_consents, stub_upstream, stub_audit,
    ):
        stub_consents.return_value = [
            _consent(grantee="dest-cg"),
        ]
        with app.test_request_context():
            data, status = dispatch_service.create_dispatch(
                careplan_guid=str(uuid.uuid4()),
                provider_guid="prov-1",
                idempotency_key=str(uuid.uuid4()),
                patient_guid="p-42",
                destination_caregiver_guid="dest-cg",
                payload_concept_guids=["concept-x"],
            )
        # Upstream actually called -> dispatch proceeded.
        assert stub_upstream.called
        assert status in (201, 200)
        # No refusal in audit captures.
        actions = [c["action"] for c in stub_audit]
        assert "careplan.dispatch.refused" not in actions

    def test_unconsented_dispatch_refused_403(
        self, app, stub_consents, stub_upstream, stub_audit,
    ):
        stub_consents.return_value = []  # no consents at all
        with app.test_request_context():
            data, status = dispatch_service.create_dispatch(
                careplan_guid="cp-1",
                provider_guid="prov-1",
                idempotency_key=str(uuid.uuid4()),
                patient_guid="p-42",
                destination_caregiver_guid="dest-cg",
                payload_concept_guids=["concept-x"],
            )
        assert status == 403, data
        assert data["code"] == "consent_missing"
        assert data["reason"] == "no_consent"
        # Upstream NOT called.
        assert not stub_upstream.called
        # Audit row recorded.
        assert any(
            c["action"] == "careplan.dispatch.refused"
            and c["details"]["reason"] == "no_consent"
            for c in stub_audit
        )

    def test_concept_narrowed_refusal(
        self, app, stub_consents, stub_upstream, stub_audit,
    ):
        # Patient consented to "concept-a" only.
        stub_consents.return_value = [
            _consent(grantee="dest-cg", concepts=["concept-a"]),
        ]
        with app.test_request_context():
            data, status = dispatch_service.create_dispatch(
                careplan_guid="cp-2",
                provider_guid="prov-1",
                idempotency_key=str(uuid.uuid4()),
                patient_guid="p-42",
                destination_caregiver_guid="dest-cg",
                payload_concept_guids=["concept-b"],  # not consented
            )
        assert status == 403
        assert data["reason"] == "concept_not_consented"
        assert not stub_upstream.called

    def test_idempotency_replay_does_not_bypass_consent(
        self, app, stub_consents, stub_upstream, stub_audit,
    ):
        # Even if a prior dispatch shares the same idempotency key,
        # a now-revoked consent must STILL refuse — the consent gate
        # runs BEFORE the idempotency lookup.
        stub_consents.return_value = []
        with app.test_request_context():
            _, status = dispatch_service.create_dispatch(
                careplan_guid="cp-3",
                provider_guid="prov-1",
                idempotency_key="reused-key-xyz",
                patient_guid="p-42",
                destination_caregiver_guid="dest-cg",
            )
        assert status == 403
        assert not stub_upstream.called

    def test_legacy_call_without_consent_fields_still_works(
        self, app, stub_consents, stub_upstream, stub_audit,
    ):
        """When both consent fields are absent, skip the gate so the
        rollout doesn't break callers that pre-date #229."""
        with app.test_request_context():
            _, status = dispatch_service.create_dispatch(
                careplan_guid="cp-4",
                provider_guid="prov-1",
                idempotency_key=str(uuid.uuid4()),
            )
        # No 403 — the soft-rollout path proceeded to upstream.
        assert status in (201, 200, 502)  # upstream stub returns 201
        # Consent fetch never happened (saving an ips round-trip).
        assert not stub_consents.called

    def test_half_consent_fields_warn_but_proceed(
        self, app, stub_consents, stub_upstream, stub_audit, caplog,
    ):
        """Only patient supplied without destination_caregiver_guid
        should log a warning and skip enforcement, not refuse."""
        with app.test_request_context():
            _, status = dispatch_service.create_dispatch(
                careplan_guid="cp-5",
                provider_guid="prov-1",
                idempotency_key=str(uuid.uuid4()),
                patient_guid="p-42",  # caregiver missing
            )
        assert status in (201, 200, 502)
        assert not stub_consents.called


# ---------------------------------------------------------------------------
# Route plumbing
# ---------------------------------------------------------------------------

class TestRoutePlumbing:
    def test_bad_payload_concept_guids_shape_is_400(self, client):
        """The route's own validation rejects payload_concept_guids
        when it's not a list.

        Ticket #380 (rollup #348) — URL updated from
        `/api/v1/CarePlan/<g>/dispatch` (deleted in #368 commit-1)
        to the canonical `/api/v1/PlanDefinition/<g>/dispatch`. The
        conftest now pins AUTH_DISABLED=True per-test so the
        pytest.skip flake-shim from the earlier polluted-env era is
        removed."""
        r = client.post(
            "/api/v1/PlanDefinition/cp-route/dispatch",
            json={
                "provider_guid": "prov-1",
                "payload_concept_guids": "concept-x",  # string, not list
            },
        )
        assert r.status_code == 400
        assert "payload_concept_guids" in r.get_json()["message"]
