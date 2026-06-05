"""Spärr (PDL Ch 4 § 4) — request.pdhc SR + dispatch read paths
(ticket #228).

Mocks ips.pdhc; the cache is invalidated between tests for isolation.
"""
from unittest.mock import patch
from datetime import datetime, timezone
import uuid

import pytest

from app import db
from app.models.service_request_models import ServiceRequest
from app.services import ips_client as ips_mod
from app.services.ips_client import Block
from app.services import service_request_service


# Two requester orgs; patient blocks ORG_BLOCKED on the SR side
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


def _block(scope_id, *, lift_kind=None, lift_concepts=None,
           lift_from=None, lift_until=None, active=True,
           patient=PATIENT):
    return Block(
        guid=str(uuid.uuid4()),
        patient_guid=patient,
        source_scope_type="clinic",
        source_scope_id=str(scope_id),
        is_active=active,
        lift_kind=lift_kind,
        lift_concept_guids=lift_concepts,
        lift_from_date=lift_from,
        lift_until_date=lift_until,
    )


@pytest.fixture(autouse=True)
def _flush_cache():
    ips_mod._cache.invalidate()
    ips_mod._cache.hits = 0
    ips_mod._cache.misses = 0
    yield
    ips_mod._cache.invalidate()


# ---------------------------------------------------------------------------
# Pure filter helpers
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_is_sr_visible_hides_blocked_requester(self):
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        assert ips_mod.is_sr_visible(SR(), [_block(ORG_BLOCKED)]) is False

    def test_is_sr_visible_passes_unblocked_requester(self):
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_OK
        assert ips_mod.is_sr_visible(SR(), [_block(ORG_BLOCKED)]) is True

    def test_is_sr_visible_lift_exposes_sr(self):
        """A lift on the blocked scope exposes the SR — the per-row
        mechanical filter applies downstream (#205/#206/#207)."""
        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        lift_block = _block(
            ORG_BLOCKED, lift_kind="indispensable_care",
            lift_concepts=[str(uuid.uuid4())],
        )
        assert ips_mod.is_sr_visible(SR(), [lift_block]) is True

    def test_is_sr_visible_caregiver_scope_ignored_in_v1(self):
        """Caregiver-scope blocks are v2 (#204); v1 must NOT hide."""
        cg_block = Block(
            guid=str(uuid.uuid4()), patient_guid=PATIENT,
            source_scope_type="caregiver", source_scope_id=ORG_BLOCKED,
            is_active=True, lift_kind=None, lift_concept_guids=None,
            lift_from_date=None, lift_until_date=None,
        )

        class SR:
            patient_guid = PATIENT
            requester_org_guid = ORG_BLOCKED
        assert ips_mod.is_sr_visible(SR(), [cg_block]) is True

    def test_filter_visible_srs_drops_blocked_ones(self):
        class SR:
            def __init__(self, org):
                self.patient_guid = PATIENT
                self.requester_org_guid = org
        srs = [SR(ORG_OK), SR(ORG_BLOCKED), SR(ORG_OK)]
        blocks = {PATIENT: [_block(ORG_BLOCKED)]}
        out = ips_mod.filter_visible_srs(srs, blocks)
        assert [s.requester_org_guid for s in out] == [ORG_OK, ORG_OK]


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

class TestCache:
    def test_hit_within_ttl(self, app):
        calls = {"n": 0}

        class Fake:
            def fetch_active_blocks(self, p):
                calls["n"] += 1
                return [_block(ORG_BLOCKED)]

        with app.app_context():
            ips_mod.get_active_blocks(PATIENT, client=Fake())
            ips_mod.get_active_blocks(PATIENT, client=Fake())
            ips_mod.get_active_blocks(PATIENT, client=Fake())
        assert calls["n"] == 1

    def test_invalidate_evicts(self, app):
        calls = {"n": 0}

        class Fake:
            def fetch_active_blocks(self, p):
                calls["n"] += 1
                return []

        with app.app_context():
            ips_mod.get_active_blocks(PATIENT, client=Fake())
            ips_mod.invalidate(PATIENT)
            ips_mod.get_active_blocks(PATIENT, client=Fake())
        assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Service-layer integration
# ---------------------------------------------------------------------------

class TestServiceLayer:
    def test_get_returns_404_when_requester_org_blocked(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_BLOCKED)
            with patch(
                "app.services.service_request_service.ips_client.get_active_blocks",
                return_value=[_block(ORG_BLOCKED)],
            ):
                data, status = service_request_service.get_service_request(sr.guid)
            assert status == 404
            assert data.get("code") == "not_found"
            # Clean up
            db.session.delete(sr)
            db.session.commit()

    def test_get_returns_200_when_unblocked(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_OK)
            with patch(
                "app.services.service_request_service.ips_client.get_active_blocks",
                return_value=[_block(ORG_BLOCKED)],
            ):
                data, status = service_request_service.get_service_request(sr.guid)
            assert status == 200
            assert data["guid"] == sr.guid
            db.session.delete(sr)
            db.session.commit()

    def test_get_returns_200_when_lift_active(self, app):
        with app.app_context():
            sr = _make_sr(requester_org=ORG_BLOCKED)
            lift_block = _block(
                ORG_BLOCKED, lift_kind="indispensable_care",
                lift_concepts=[str(uuid.uuid4())],
            )
            with patch(
                "app.services.service_request_service.ips_client.get_active_blocks",
                return_value=[lift_block],
            ):
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
            with patch(
                "app.services.service_request_service.ips_client.fetch_blocks_for_patients",
                return_value={PATIENT: [_block(ORG_BLOCKED)]},
            ):
                data, status = service_request_service.list_service_requests(
                    is_su_admin=True,
                )
            assert status == 200
            assert len(data["items"]) == 2
            visible_orgs = [i["requester_org_guid"] for i in data["items"]]
            assert all(o == ORG_OK for o in visible_orgs)
            for sr in srs:
                db.session.delete(sr)
            db.session.commit()

    def test_list_passes_through_without_blocks(self, app):
        with app.app_context():
            srs = [_make_sr(requester_org=ORG_OK) for _ in range(3)]
            with patch(
                "app.services.service_request_service.ips_client.fetch_blocks_for_patients",
                return_value={},
            ):
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
            with patch(
                "app.services.service_request_service.ips_client.fetch_blocks_for_patients",
                return_value={PATIENT: [_block(ORG_BLOCKED)]},
            ):
                data, status = service_request_service.list_service_requests(
                    is_su_admin=True,
                )
            # 2 in DB; 1 visible after spärr.
            assert data["total"] == 2
            assert len(data["items"]) == 1
            for sr in srs:
                db.session.delete(sr)
            db.session.commit()
