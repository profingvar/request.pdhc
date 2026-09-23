"""Ticket #582 — a request archives itself once no provider has open work.

"When a provider says the patient is finished, the request is automatically
archived." One provider finishing is not sufficient on its own: a
ServiceRequest can be matched to several providers, and archiving while
another is still working would pull live work out of that provider's feed
(#582's own first clause). So the SR archives only when EVERY match is
terminal — completed or rejected.
"""
import uuid

from app import db
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch,
)
from app.services import completion_service


def _mk_sr(status='active'):
    sr = ServiceRequest(
        guid=str(uuid.uuid4()),
        status=status,
        patient_guid=str(uuid.uuid4()),
        plan_definition_guid=str(uuid.uuid4()),
        plan_definition_snapshot={'title': 'T'},
        contract_guid=str(uuid.uuid4()),
        requester_user_guid=str(uuid.uuid4()),
    )
    db.session.add(sr)
    db.session.flush()
    return sr


def _mk_match(sr, status='sent', provider_guid=None):
    m = ServiceRequestContractMatch(
        service_request_guid=sr.guid,
        contract_guid=sr.contract_guid,
        provider_org_guid=provider_guid or str(uuid.uuid4()),
        status=status,
    )
    db.session.add(m)
    db.session.flush()
    return m


class TestAutoArchiveOnCompletion:

    def test_sole_provider_completing_archives_the_request(self, app):
        with app.app_context():
            sr = _mk_sr()
            _mk_match(sr, 'accepted')
            db.session.commit()

            result, status = completion_service.mark_service_request_completed(sr.guid)
            assert status == 200
            assert result['archived'] is True
            assert db.session.get(ServiceRequest, sr.id).status == 'archived'

    def test_all_providers_terminal_archives_even_when_one_rejected(self, app):
        with app.app_context():
            sr = _mk_sr()
            _mk_match(sr, 'rejected')      # terminal, stays rejected
            _mk_match(sr, 'accepted')      # this one gets completed
            db.session.commit()

            result, _ = completion_service.mark_service_request_completed(sr.guid)
            assert result['matches_updated'] == 1
            assert result['archived'] is True
            assert db.session.get(ServiceRequest, sr.id).status == 'archived'

    def test_request_with_no_matches_is_not_archived(self, app):
        # Nothing was ever dispatched — that is the expiry path, not this one.
        with app.app_context():
            sr = _mk_sr()
            db.session.commit()

            result, _ = completion_service.mark_service_request_completed(sr.guid)
            assert result['archived'] is False
            assert db.session.get(ServiceRequest, sr.id).status == 'active'

    def test_draft_is_never_archived_by_this_path(self, app):
        with app.app_context():
            sr = _mk_sr(status='draft')
            _mk_match(sr, 'accepted')
            db.session.commit()

            result, _ = completion_service.mark_service_request_completed(sr.guid)
            assert result['archived'] is False
            assert db.session.get(ServiceRequest, sr.id).status == 'draft'

    def test_idempotent_second_call_does_not_rearchive(self, app):
        with app.app_context():
            sr = _mk_sr()
            _mk_match(sr, 'accepted')
            db.session.commit()

            first, _ = completion_service.mark_service_request_completed(sr.guid)
            second, status = completion_service.mark_service_request_completed(sr.guid)
            assert first['archived'] is True
            assert second['archived'] is False      # already archived, no-op
            assert status == 200
            assert db.session.get(ServiceRequest, sr.id).status == 'archived'


class TestArchivedRequestLeavesTheFeed:

    def test_completion_removes_it_from_the_provider_feed(self, app):
        """The two halves of #582 meeting: completion archives, and archiving
        takes the request out of the provider's active feed."""
        from app.services import provider_feed_service

        provider_guid = str(uuid.uuid4())
        with app.app_context():
            sr = _mk_sr()
            _mk_match(sr, 'accepted', provider_guid=provider_guid)
            db.session.commit()

            before, _ = provider_feed_service.list_for_provider(provider_guid)
            assert sr.guid in [i['service_request_guid'] for i in before['items']]

            completion_service.mark_service_request_completed(sr.guid)

            after, _ = provider_feed_service.list_for_provider(provider_guid)
            assert sr.guid not in [i['service_request_guid'] for i in after['items']]

    def test_but_it_is_still_downloadable_for_a_late_report(self, app):
        """#90's guarantee survives: the provider can still fetch and submit."""
        from app.services import provider_feed_service

        provider_guid = str(uuid.uuid4())
        with app.app_context():
            sr = _mk_sr()
            sr.fhir_resource = {'resourceType': 'ServiceRequest', 'id': 'x'}
            _mk_match(sr, 'accepted', provider_guid=provider_guid)
            db.session.commit()

            completion_service.mark_service_request_completed(sr.guid)

            data, status = provider_feed_service.download_bundle(
                service_request_guid=sr.guid,
                provider_org_guid=provider_guid,
                contract_guid=sr.contract_guid,
            )
            assert status == 200
            assert data['sr_status'] == 'archived'
