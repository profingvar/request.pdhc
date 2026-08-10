"""Spärr (PDL Ch 4 § 4) — request.pdhc SR read paths (ticket #228).

Exercises the check-based spärr filter (2026-08-10 auth fix: switched from the
clinic-gated /blocks list + X-API-Key to the cross-service /blocks/check
predicate + Authorization: ApiKey). ips.pdhc is stubbed with a fake client;
the cache is invalidated between tests for isolation.
"""
from unittest.mock import patch
from datetime import datetime, timezone
import uuid

import pytest

from app import db
from app.models.service_request_models import ServiceRequest
from app.services import ips_client as ips_mod
from app.services.ips_client import SprCheck
from app.services import service_request_service


ORG_OK = str(uuid.uuid4())
ORG_BLOCKED = str(uuid.uuid4())
PATIENT = str(uuid.uuid4())
PLANDEF = str(uuid.uuid4())
USER = str(uuid.uuid4())


def _make_sr(*, requester_org, status="active", patient=PATIENT):
    """Insert a minimal SR row."""
    sr = ServiceRequest(
        guid=str(uuid.uuid4()),
        status=status,
        patient_guid=patient,
        plan_definition_guid=PLANDEF,
        requester_user_guid=USER,
        requester_org_guid=requester_org,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(sr)
    db.session.commit()
    return sr


def _scopes(org, *, lift_kind=None):
    """A blocking_scopes payload as ips /blocks/check would return it."""
    return [{
        "scope_type": "clinic",
        "scope_id": str(org),
        "block_guid": str(uuid.uuid4()),
        "lift_kind": lift_kind,
        "lift_concept_guids": [str(uuid.uuid4())] if lift_kind else None,
        "lift_from_date": None,
        "lift_until_date": None,
        "lift_expires_at": None,
    }]


class FakeClient:
    """Stub for ips.pdhc /blocks/check.

    ``blocked``: ``{(patient_guid, org_guid): (is_blocked, scopes)}``.
    Any (patient, org) not in the map answers "not blocked" — which is exactly
    how the real endpoint behaves for an unblocked source or a caregiver-only
    block (we never pass source_caregiver_id, so caregiver blocks never match).
    """
    def __init__(self, blocked=None):
        self.blocked = blocked or {}
        self.calls = 0

    def check_block(self, patient_guid, source_clinic_id):
        self.calls += 1
        return self.blocked.get((patient_guid, source_clinic_id), (False, []))


@pytest.fixture(autouse=True)
def _flush_cache():
    ips_mod._cache.invalidate()
    ips_mod._cache.hits = 0
    ips_mod._cache.misses = 0
    yield
    ips_mod._cache.invalidate()


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_hides_blocked_requester(self):
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
        assert ips_mod.is_sr_visible(SR(), client=fake) is False

    def test_passes_unblocked_requester(self):
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_OK
        # Patient is blocked for a DIFFERENT org; the check for ORG_OK is clean.
        fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
        assert ips_mod.is_sr_visible(SR(), client=fake) is True

    def test_lift_exposes_sr(self):
        """A lift on the blocked scope exposes the SR — the per-observation
        mechanical filter applies downstream (#205/#206/#207)."""
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        fake = FakeClient({
            (PATIENT, ORG_BLOCKED):
                (True, _scopes(ORG_BLOCKED, lift_kind="indispensable_care")),
        })
        assert ips_mod.is_sr_visible(SR(), client=fake) is True

    def test_caregiver_only_block_does_not_hide_v1(self):
        """Caregiver-scope blocks are v2 (#204). We pass only source_clinic_id,
        so /blocks/check never matches a caregiver block → not blocked."""
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        fake = FakeClient({})  # check answers (False, []) for the clinic id
        assert ips_mod.is_sr_visible(SR(), client=fake) is True

    def test_missing_patient_or_org_is_visible(self):
        class SR:
            patient_guid = None
            requester_org_guid = ORG_BLOCKED
        fake = FakeClient({(None, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
        assert ips_mod.is_sr_visible(SR(), client=fake) is True
        assert fake.calls == 0  # short-circuits before any lookup

    def test_filter_visible_srs_drops_blocked_ones(self):
        class SR:
            def __init__(self, org):
                self.patient_guid = PATIENT
                self.requester_org_guid = org
        srs = [SR(ORG_OK), SR(ORG_BLOCKED), SR(ORG_OK)]
        fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
        out = ips_mod.filter_visible_srs(srs, client=fake)
        assert [s.requester_org_guid for s in out] == [ORG_OK, ORG_OK]


# ---------------------------------------------------------------------------
# Transport (header + endpoint)
# ---------------------------------------------------------------------------

class TestTransport:
    def test_uses_authorization_apikey_and_check_endpoint(self):
        from app.services.ips_client import IpsClient
        captured = {}

        class Resp:
            status_code = 200
            def json(self):
                return {"is_blocked": True,
                        "blocking_scopes": _scopes(ORG_BLOCKED)}

        def fake_get(url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return Resp()

        c = IpsClient(api_key="RAWKEY123", base_url="https://ips.pdhc.se")
        with patch("app.services.ips_client.requests.get", fake_get):
            is_blocked, scopes = c.check_block(PATIENT, ORG_BLOCKED)

        assert is_blocked is True and len(scopes) == 1
        assert captured["url"].endswith(f"/patients/{PATIENT}/blocks/check")
        assert captured["params"] == {"source_clinic_id": ORG_BLOCKED}
        assert captured["headers"]["Authorization"] == "ApiKey RAWKEY123"
        assert "X-API-Key" not in captured["headers"]

    def test_4xx_fails_open_to_not_blocked(self):
        from app.services.ips_client import IpsClient

        class Resp:
            status_code = 401
            text = "nope"
            def json(self):
                return {}

        c = IpsClient(api_key="k", base_url="https://ips.pdhc.se")
        with patch("app.services.ips_client.requests.get", return_value=Resp()):
            assert c.check_block(PATIENT, ORG_BLOCKED) == (False, [])


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestCache:
    def test_hit_within_ttl(self, app):
        fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
        with app.app_context():
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
        assert fake.calls == 1

    def test_distinct_org_is_distinct_key(self, app):
        fake = FakeClient({})
        with app.app_context():
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
            ips_mod.get_sr_check(PATIENT, ORG_OK, client=fake)
        assert fake.calls == 2  # different (patient, org) → separate lookups

    def test_invalidate_evicts_all_orgs_for_patient(self, app):
        fake = FakeClient({})
        with app.app_context():
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
            ips_mod.get_sr_check(PATIENT, ORG_OK, client=fake)
            ips_mod.invalidate(PATIENT)
            ips_mod.get_sr_check(PATIENT, ORG_BLOCKED, client=fake)
        assert fake.calls == 3  # 2 before + 1 after eviction


# ---------------------------------------------------------------------------
# Service-layer integration
# ---------------------------------------------------------------------------

class TestServiceLayer:
    def test_get_returns_404_when_requester_org_blocked(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_BLOCKED)
            fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.get_service_request(sr.guid)
            assert status == 404
            assert data.get("code") == "not_found"
            db.session.delete(sr)
            db.session.commit()

    def test_get_returns_200_when_unblocked(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_OK)
            fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.get_service_request(sr.guid)
            assert status == 200
            assert data["guid"] == sr.guid
            db.session.delete(sr)
            db.session.commit()

    def test_get_returns_200_when_lift_active(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_BLOCKED)
            fake = FakeClient({
                (PATIENT, ORG_BLOCKED):
                    (True, _scopes(ORG_BLOCKED, lift_kind="indispensable_care")),
            })
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.get_service_request(sr.guid)
            assert status == 200
            db.session.delete(sr)
            db.session.commit()

    def test_list_filters_blocked_srs(self, app):
        with app.app_context():
            srs = [
                _make_sr(requester_org=ORG_OK),
                _make_sr(requester_org=ORG_BLOCKED),
                _make_sr(requester_org=ORG_OK),
            ]
            fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.list_service_requests(
                    is_su_admin=True,
                )
            assert status == 200
            assert len(data["items"]) == 2
            assert all(i["requester_org_guid"] == ORG_OK for i in data["items"])
            for sr in srs:
                db.session.delete(sr)
            db.session.commit()

    def test_list_passes_through_without_blocks(self, app):
        with app.app_context():
            srs = [_make_sr(requester_org=ORG_OK) for _ in range(3)]
            fake = FakeClient({})
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.list_service_requests(
                    is_su_admin=True,
                )
            assert status == 200
            assert len(data["items"]) == 3
            for sr in srs:
                db.session.delete(sr)
            db.session.commit()

    def test_list_total_uses_unfiltered_count(self, app):
        """Exposing the spärr-filtered count would leak 'the patient has
        blocks'. ``total`` must stay the unfiltered query count."""
        with app.app_context():
            srs = [
                _make_sr(requester_org=ORG_OK),
                _make_sr(requester_org=ORG_BLOCKED),
            ]
            fake = FakeClient({(PATIENT, ORG_BLOCKED): (True, _scopes(ORG_BLOCKED))})
            with patch("app.services.ips_client._default_client", return_value=fake):
                data, status = service_request_service.list_service_requests(
                    is_su_admin=True,
                )
            assert data["total"] == 2
            assert len(data["items"]) == 1
            for sr in srs:
                db.session.delete(sr)
            db.session.commit()
