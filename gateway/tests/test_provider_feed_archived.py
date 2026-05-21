"""Tests for ticket #90 — archived SRs remain searchable/downloadable
from the provider feed, and the feed exposes period_end so providers
know the submission cutoff.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services import provider_feed_service


def _mk_sr(status, period_end=None, fhir_resource=None):
    sr = ServiceRequest(
        guid=str(uuid.uuid4()),
        status=status,
        patient_guid=str(uuid.uuid4()),
        plan_definition_guid=str(uuid.uuid4()),
        plan_definition_snapshot={'title': 'Test SR'},
        contract_guid=str(uuid.uuid4()),
        requester_user_guid=str(uuid.uuid4()),
        period_end=period_end,
        fhir_resource=fhir_resource,
    )
    db.session.add(sr)
    db.session.flush()
    return sr


def _mk_match(sr, provider_guid, match_status='sent'):
    match = ServiceRequestContractMatch(
        service_request_guid=sr.guid,
        contract_guid=sr.contract_guid,
        provider_org_guid=provider_guid,
        status=match_status,
    )
    db.session.add(match)
    db.session.flush()
    return match


class TestFeedIncludesArchived:

    def test_archived_sr_appears_in_feed(self, app):
        provider_guid = str(uuid.uuid4())
        with app.app_context():
            past = datetime.now(timezone.utc) - timedelta(days=1)
            sr = _mk_sr('archived', period_end=past.replace(tzinfo=None))
            _mk_match(sr, provider_guid, match_status='accepted')
            db.session.commit()

            data, status = provider_feed_service.list_for_provider(
                provider_org_guid=provider_guid,
            )
            assert status == 200
            guids = [item['service_request_guid'] for item in data['items']]
            assert sr.guid in guids

    def test_feed_entry_exposes_period_end_and_sr_status(self, app):
        provider_guid = str(uuid.uuid4())
        with app.app_context():
            past = datetime.now(timezone.utc) - timedelta(hours=3)
            sr = _mk_sr('archived', period_end=past.replace(tzinfo=None))
            _mk_match(sr, provider_guid, match_status='accepted')
            db.session.commit()

            data, _ = provider_feed_service.list_for_provider(
                provider_org_guid=provider_guid,
            )
            entry = next(i for i in data['items'] if i['service_request_guid'] == sr.guid)
            assert entry['sr_status'] == 'archived'
            assert entry['period_end'] is not None

    def test_draft_sr_still_excluded_from_feed(self, app):
        provider_guid = str(uuid.uuid4())
        with app.app_context():
            sr = _mk_sr('draft')
            _mk_match(sr, provider_guid, match_status='pending')
            db.session.commit()

            data, _ = provider_feed_service.list_for_provider(
                provider_org_guid=provider_guid,
            )
            guids = [item['service_request_guid'] for item in data['items']]
            assert sr.guid not in guids


class TestDownloadOfArchived:

    def test_archived_sr_is_downloadable(self, app):
        provider_guid = str(uuid.uuid4())
        with app.app_context():
            past = datetime.now(timezone.utc) - timedelta(days=2)
            sr = _mk_sr(
                'archived',
                period_end=past.replace(tzinfo=None),
                fhir_resource={'resourceType': 'ServiceRequest', 'id': 'x'},
            )
            _mk_match(sr, provider_guid, match_status='accepted')
            db.session.commit()

            data, status = provider_feed_service.download_bundle(
                service_request_guid=sr.guid,
                provider_org_guid=provider_guid,
                contract_guid=sr.contract_guid,
            )
            assert status == 200
            assert data['sr_status'] == 'archived'
            assert data['period_end'] is not None
            assert 'fhir_resource' in data
            assert 'grant_token' in data

    def test_draft_sr_download_rejected(self, app):
        provider_guid = str(uuid.uuid4())
        with app.app_context():
            sr = _mk_sr(
                'draft',
                fhir_resource={'resourceType': 'ServiceRequest'},
            )
            _mk_match(sr, provider_guid, match_status='pending')
            db.session.commit()

            data, status = provider_feed_service.download_bundle(
                service_request_guid=sr.guid,
                provider_org_guid=provider_guid,
                contract_guid=sr.contract_guid,
            )
            assert status == 400
            assert data['code'] == 'invalid_status'
