"""#1054 (record.pdhc stage 2): versioned orders, the lock after draft, and
the JournalBestallning fields.

Through the real routes and service functions; only ips/plan lookups are
stubbed. The FHIR R5 shape is checked with fhir.resources 8 (R5) where it is
installed (requirements-test.txt), and structurally in every case.
"""
import copy

import pytest
from sqlalchemy import text

from app import db
from app.models.audit_models import AuditLog
from app.models.care_plan_models import CarePlan
from app.models.history_models import CarePlanHistory, ServiceRequestHistory
from app.models.service_request_models import (
    ServiceRequest, ServiceRequestContractMatch)
from app.services import service_request_service as svc
from app.services import scope_service, sr_journal, versioning
from app.services.history_guard import HistoryIsAppendOnly, history_purge

PATIENT = "11111054-0000-4000-8000-000000000001"
OTHER = "22221054-0000-4000-8000-000000000002"
ENC = "33331054-0000-4000-8000-000000000003"
COND = "44441054-0000-4000-8000-000000000004"
CI = "55551054-0000-4000-8000-000000000005"
PLAN = {"title": "Glukoskontroll", "goals": [], "activities": []}


@pytest.fixture
def stubs(monkeypatch):
    monkeypatch.setattr('app.services.service_request_service.patient_service.get_patient',
                        lambda g: ({'id': g}, 200))
    monkeypatch.setattr(
        'app.services.service_request_service.plan_definition_service.get_plan_definition',
        lambda g: (copy.deepcopy({**PLAN, 'id': g}), 200))
    monkeypatch.setattr('app.services.service_request_service.build_patient_excerpt',
                        lambda d: {})
    monkeypatch.setattr(
        'app.services.service_request_service.patient_service.get_patient_clinic_orgs',
        lambda g: ([('clinic-1054', 'org-1054')], 200))
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda g: None)


def _create(patient=PATIENT, **journal):
    body, st = svc.create_service_request(patient_guid=patient, plan_definition_guid='pd-1054',
                                          user_guid='u-author', user_name='Dr Test',
                                          org_guid='org-1054', journal=journal)
    assert st == 201, body
    return ServiceRequest.query.filter_by(guid=body['guid']).one()


def _active(**journal):
    sr = _create(**journal)
    body, st = svc.finalize_service_request(sr.guid, user_guid='u-final')
    assert st == 200, body
    db.session.expire_all()
    return ServiceRequest.query.filter_by(guid=sr.guid).one()


def _hist(guid):
    db.session.expire_all()
    return (ServiceRequestHistory.query.filter_by(service_request_guid=guid)
            .order_by(ServiceRequestHistory.version).all())


def _r5_valid(resource):
    """R5 validation where fhir.resources is installed; structural always."""
    assert resource['resourceType'] in ('ServiceRequest', 'CarePlan', 'Task')
    assert resource.get('status') and resource.get('id')
    fr = pytest.importorskip('fhir.resources', reason='pip install -r requirements-test.txt')
    del fr
    from fhir.resources import get_fhir_model_class
    get_fhir_model_class(resource['resourceType']).model_validate(resource)


# ── history ───────────────────────────────────────────────────────────────

class TestHistory:
    def test_create_is_version_1_with_its_author_and_no_history(self, stubs):
        sr = _create()
        assert (sr.version, sr.version_author_guid, sr.version_reason) == (1, 'u-author', 'created')
        assert _hist(sr.guid) == []

    def test_finalize_writes_the_draft_as_version_1(self, stubs):
        sr = _active()
        (h,) = _hist(sr.guid)
        assert (h.version, h.status, h.fhir_resource) == (1, 'draft', None)
        assert h.row['status'] == 'draft' and h.row['guid'] == sr.guid
        assert (h.changed_by_user_guid, h.change_action) == ('u-final', 'finalize')
        assert h.version_author_guid == 'u-author'
        assert (sr.version, sr.version_author_guid) == (2, 'u-final')

    def test_every_status_change_is_audited_with_who(self, stubs):
        sr = _active()
        svc.archive_service_request(sr.guid, user_guid='u-arch')
        rows = AuditLog.query.filter_by(action='service_request.status_changed',
                                        resource_guid=sr.guid).order_by(AuditLog.id).all()
        assert [(r.details['from'], r.details['to'], r.user_guid) for r in rows] == [
            ('draft', 'active', 'u-final'), ('active', 'archived', 'u-arch')]
        assert all(r.data_subject_guid == PATIENT for r in rows)

    def test_auto_archive_now_audited_and_versioned(self, stubs):
        from datetime import datetime, timedelta, timezone
        sr = _active()
        # expired validity period, forced with a Core UPDATE (period_end is
        # locked after draft, as it should be)
        db.session.execute(ServiceRequest.__table__.update()
                           .where(ServiceRequest.__table__.c.guid == sr.guid)
                           .values(period_end=datetime.now(timezone.utc) - timedelta(days=1)))
        db.session.commit()
        db.session.expire_all()
        assert svc.check_auto_archive() == 1
        h = _hist(sr.guid)[-1]
        assert h.change_action == 'auto_archive_expired'
        assert AuditLog.query.filter_by(action='service_request.auto_archive',
                                        resource_guid=sr.guid).count() == 1

    def test_an_unannotated_change_is_marked_unattributed(self, stubs):
        sr = _active()
        sr.notes = 'changed without saying who'
        db.session.commit()
        assert _hist(sr.guid)[-1].change_action.startswith('unattributed:')

    def test_no_change_no_version(self, stubs):
        sr = _active()
        sr.status = 'active'
        db.session.commit()
        assert len(_hist(sr.guid)) == 1

    def test_care_plan_update_leaves_a_version(self, client, stubs):
        sr = _create()
        cp = CarePlan.query.filter_by(guid=sr.care_plan_guid).one()
        r = client.put(f'/api/v1/careplans/{cp.guid}', json={'status': 'on-hold'})
        assert r.status_code == 200, r.get_json()
        db.session.expire_all()
        (h,) = CarePlanHistory.query.filter_by(care_plan_guid=cp.guid).all()
        assert (h.version, h.status, h.change_action) == (1, 'active', 'update')
        assert CarePlan.query.filter_by(guid=cp.guid).one().version == 2


class TestHistoryIsAppendOnly:
    def _row(self, stubs):
        sr = _active()
        return _hist(sr.guid)[0]

    def test_orm_update_refused(self, stubs):
        h = self._row(stubs)
        h.status = 'tampered'
        with pytest.raises(HistoryIsAppendOnly):
            db.session.commit()
        db.session.rollback()

    def test_orm_delete_refused(self, stubs):
        h = self._row(stubs)
        db.session.delete(h)
        with pytest.raises(HistoryIsAppendOnly):
            db.session.commit()
        db.session.rollback()

    @pytest.mark.parametrize('sql', [
        "UPDATE service_request_history SET status = 'tampered'",
        "DELETE FROM service_request_history",
        "UPDATE care_plan_history SET status = 'tampered'",
    ])
    def test_raw_sql_refused_by_the_database(self, stubs, sql):
        self._row(stubs)
        client_cp = CarePlan.query.first()
        versioning.note_change(client_cp, 'u', 'x', 'x')
        client_cp.title = 'v2'
        db.session.commit()
        with pytest.raises(Exception, match='append-only'):
            db.session.execute(text(sql))
        db.session.rollback()
        assert ServiceRequestHistory.query.filter_by(status='tampered').count() == 0

    def test_bulk_query_delete_refused(self, stubs):
        self._row(stubs)
        with pytest.raises(Exception, match='append-only'):
            ServiceRequestHistory.query.delete()
        db.session.rollback()

    def test_purge_allows_delete_only_and_does_not_outlive_itself(self, stubs):
        self._row(stubs)
        with pytest.raises(Exception, match='append-only'):
            with history_purge(db.session):
                db.session.execute(text("UPDATE service_request_history SET status='x'"))
        with history_purge(db.session):
            db.session.execute(text("DELETE FROM service_request_history"))
        assert ServiceRequestHistory.query.count() == 0
        sr = _active()
        assert _hist(sr.guid)
        with pytest.raises(Exception, match='append-only'):
            db.session.execute(text("DELETE FROM service_request_history"))
        db.session.rollback()


# ── the lock after draft ──────────────────────────────────────────────────

class TestLock:
    def test_orm_change_of_a_locked_field_is_refused(self, stubs):
        sr = _active()
        sr.priority = 'stat'
        with pytest.raises(versioning.ServiceRequestLocked) as e:
            db.session.commit()
        db.session.rollback()
        assert e.value.fields == ['priority']
        db.session.expire_all()
        assert ServiceRequest.query.filter_by(guid=sr.guid).one().priority == 'routine'
        assert len(_hist(sr.guid)) == 1

    def test_draft_changes_freely(self, stubs):
        sr = _create()
        sr.priority = 'urgent'
        db.session.commit()
        assert sr.priority == 'urgent' and len(_hist(sr.guid)) == 1

    def test_patch_on_a_sent_order_is_409_with_how_to_replace(self, client, stubs):
        sr = _active()
        r = client.patch(f'/api/v1/ServiceRequest/{sr.guid}', json={'priority': 'stat'})
        assert r.status_code == 409
        body = r.get_json()
        assert body['code'] == 'service_request_locked'
        assert body['locked_fields'] == ['priority']
        assert body['replace_with']['body'] == {'replaces': [sr.guid]}

    def test_note_on_a_sent_order_is_appended_and_versioned(self, client, stubs):
        sr = _active()
        r = client.patch(f'/api/v1/ServiceRequest/{sr.guid}', json={'note': 'Ring patienten'})
        assert r.status_code == 200, r.get_json()
        body = r.get_json()
        assert body['annotations'][0]['text'] == 'Ring patienten'
        assert body['annotations'][0]['author_guid'] == 'dev-admin-guid'
        assert body['version'] == 3
        assert _hist(sr.guid)[-1].change_action == 'add_note'
        v3 = client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/3').get_json()
        assert v3['note'][-1]['text'] == 'Ring patienten'

    def test_draft_patch_sets_journal_fields(self, client, stubs):
        sr = _create()
        r = client.patch(f'/api/v1/ServiceRequest/{sr.guid}',
                         json={'reason': [{'reference': f'Condition/{COND}'}],
                               'encounter_guid': ENC, 'priority': 'urgent'})
        assert r.status_code == 200, r.get_json()
        assert r.get_json()['encounter_guid'] == ENC

    def test_patch_status_points_to_the_status_routes(self, client, stubs):
        sr = _active()
        r = client.patch(f'/api/v1/ServiceRequest/{sr.guid}', json={'status': 'completed'})
        assert (r.status_code, r.get_json()['code']) == (400, 'use_status_route')

    def test_snapshot_and_forms_edits_are_409(self, client, stubs):
        sr = _active()
        r = client.put(f'/api/v1/ServiceRequest/{sr.guid}/snapshot',
                       json={'plan_definition_snapshot': {}})
        assert (r.status_code, r.get_json()['code']) == (409, 'service_request_locked')
        r = client.post(f'/api/v1/ServiceRequest/{sr.guid}/forms', json={'form_guid': 'f1'})
        assert (r.status_code, r.get_json()['code']) == (409, 'service_request_locked')

    def test_no_return_to_draft_and_revoked_stays_revoked(self, client, stubs):
        sr = _active()
        sr.status = 'draft'
        with pytest.raises(versioning.ServiceRequestLocked):
            db.session.commit()
        db.session.rollback()
        assert client.post(f'/api/v1/ServiceRequest/{sr.guid}/revoke').status_code == 200
        r = client.post(f'/api/v1/ServiceRequest/{sr.guid}/archive')
        assert r.status_code == 409

    def test_a_sent_order_cannot_be_deleted(self, stubs):
        sr = _active()
        db.session.delete(sr)
        with pytest.raises(versioning.ServiceRequestLocked):
            db.session.commit()
        db.session.rollback()

    def test_contract_is_set_once_never_changed(self, stubs):
        sr = _active()
        sr.contract_guid = 'contract-1'
        db.session.commit()
        sr.contract_guid = 'contract-2'
        with pytest.raises(versioning.ServiceRequestLocked):
            db.session.commit()
        db.session.rollback()

    def test_dispatch_still_works_on_a_sent_order(self, stubs, monkeypatch):
        from app.services import match_service
        monkeypatch.setattr('app.services.push_service.push_to_provider',
                            lambda *a, **k: ({'status': 'sent'}, 200))
        sr = _active()
        body, st = match_service.dispatch_to_provider(sr.guid, 'contract-d', 'prov-1',
                                                      user_guid='u-disp')
        assert st == 200, body
        db.session.expire_all()
        assert ServiceRequest.query.filter_by(guid=sr.guid).one().contract_guid == 'contract-d'
        assert _hist(sr.guid)[-1].change_action == 'dispatch'

    def test_the_web_handler_turns_a_lock_into_409_not_500(self, client, stubs, monkeypatch):
        """A path that forgets the rule hits the before_flush hook; the app's
        error handler answers 409 by name."""
        sr = _active()

        def careless(guid, payload, **kw):
            row = ServiceRequest.query.filter_by(guid=guid).one()
            row.priority = 'stat'
            db.session.commit()
            return {}, 200
        monkeypatch.setattr(svc, 'patch_service_request', careless)
        r = client.patch(f'/api/v1/ServiceRequest/{sr.guid}', json={'note': 'x'})
        assert r.status_code == 409 and r.get_json()['code'] == 'service_request_locked'
        db.session.expire_all()
        assert ServiceRequest.query.filter_by(guid=sr.guid).one().priority == 'routine'


# ── JournalBestallning fields ──────────────────────────────────────────────

class TestJournalFields:
    def test_fields_reach_the_r5_resource(self, stubs):
        sr = _active(reason=[{'concept': {'text': 'Misstänkt diabetes'}},
                             {'reference': f'Condition/{COND}/_history/2'}],
                     encounter_guid=ENC, supporting_info=[f'ClinicalImpression/{CI}'])
        res = sr.fhir_resource
        assert res['identifier'] == [{'system': sr_journal.IDENTIFIER_SYSTEM, 'value': sr.guid}]
        assert res['reason'][1] == {'reference': {'reference': f'Condition/{COND}/_history/2'}}
        assert res['encounter']['reference'] == f'Encounter/{ENC}'
        assert {'reference': {'reference': f'ClinicalImpression/{CI}'}} in res['supportingInfo']
        _r5_valid(res)

    @pytest.mark.parametrize('journal,code', [
        ({'reason': [{'reference': f'Patient/{COND}'}]}, 'invalid_reason'),
        ({'reason': [{'concept': {}}]}, 'invalid_reason'),
        ({'encounter_guid': 'not-a-guid'}, 'invalid_encounter'),
        ({'supporting_info': ['nonsense']}, 'invalid_supporting_info'),
        ({'replaces': ['nope']}, 'invalid_replaces'),
    ])
    def test_invalid_fields_are_refused(self, stubs, journal, code):
        body, st = svc.create_service_request(patient_guid=PATIENT, plan_definition_guid='pd',
                                              user_guid='u', org_guid='org-1054', journal=journal)
        assert (st, body['code']) == (400, code)
        assert ServiceRequest.query.count() == 0

    def test_journal_order_needs_reason_or_note(self, stubs):
        sr = _create(encounter_guid=ENC)
        body, st = svc.finalize_service_request(sr.guid, user_guid='u')
        assert (st, body['code']) == (409, 'reason_or_note_required')
        sr2 = _create(encounter_guid=ENC, reason=[{'concept': {'text': 'Kontroll'}}])
        assert svc.finalize_service_request(sr2.guid, user_guid='u')[1] == 200

    def test_ordinary_order_without_encounter_is_not_held_to_it(self, stubs):
        assert _active().status == 'active'

    def test_revocation_reason_is_recorded(self, client, stubs):
        sr = _active()
        r = client.post(f'/api/v1/ServiceRequest/{sr.guid}/revoke', json={'reason': 'Fel patient'})
        assert r.status_code == 200
        body = r.get_json()
        assert body['status'] == 'revoked'
        assert body['annotations'][-1]['text'] == 'Makulerad: Fel patient'
        assert body['annotations'][-1]['kind'] == 'revocation'
        h = _hist(sr.guid)[-1]
        assert (h.status, h.change_reason, h.change_action) == ('active', 'Fel patient', 'revoke')
        audit = AuditLog.query.filter_by(action='service_request.revoke',
                                         resource_guid=sr.guid).one()
        assert audit.details['reason'] == 'Fel patient'

    def test_journal_order_revoke_requires_reason(self, client, stubs):
        sr = _active(encounter_guid=ENC, reason=[{'concept': {'text': 'x'}}])
        r = client.post(f'/api/v1/ServiceRequest/{sr.guid}/revoke')
        assert (r.status_code, r.get_json()['code']) == (400, 'revocation_reason_required')


class TestReplaces:
    def test_replaced_order_is_revoked_when_the_replacement_is_sent(self, stubs):
        old = _active()
        new = _create(replaces=[old.guid])
        db.session.expire_all()
        assert ServiceRequest.query.filter_by(guid=old.guid).one().status == 'active'
        body, st = svc.finalize_service_request(new.guid, user_guid='u-repl')
        assert st == 200, body
        db.session.expire_all()
        old_now = ServiceRequest.query.filter_by(guid=old.guid).one()
        assert old_now.status == 'revoked'
        assert old_now.annotations[-1]['text'] == f'Makulerad: ersatt av beställning {new.guid}'
        h = _hist(old.guid)[-1]
        assert (h.status, h.change_action, h.changed_by_user_guid) == ('active', 'replaced', 'u-repl')
        assert body['fhir_resource']['replaces'] == [{'reference': f'ServiceRequest/{old.guid}'}]

    def test_other_patient_draft_and_terminal_are_refused(self, stubs):
        a = _create(patient=OTHER)
        svc.finalize_service_request(a.guid, user_guid='u')
        for target, code in ((a.guid, 'replaces_other_patient'),
                             (_create().guid, 'replaces_draft')):
            body, st = svc.create_service_request(
                patient_guid=PATIENT, plan_definition_guid='pd', user_guid='u',
                org_guid='org-1054', journal={'replaces': [target]})
            assert (st, body['code']) == (409, code)
        b = _active()
        svc.revoke_service_request(b.guid, user_guid='u')
        body, st = svc.create_service_request(
            patient_guid=PATIENT, plan_definition_guid='pd', user_guid='u',
            org_guid='org-1054', journal={'replaces': [b.guid]})
        assert (st, body['code']) == (409, 'replaces_terminal')

    def test_accepted_match_blocks_the_replacement_and_nothing_changes(self, stubs):
        old = _active()
        db.session.add(ServiceRequestContractMatch(service_request_guid=old.guid,
                                                   contract_guid='c', provider_org_guid='p',
                                                   status='accepted'))
        db.session.commit()
        new = _create(replaces=[old.guid])
        body, st = svc.finalize_service_request(new.guid, user_guid='u')
        assert (st, body['code']) == (409, 'replaced_has_accepted')
        db.session.expire_all()
        assert ServiceRequest.query.filter_by(guid=new.guid).one().status == 'draft'
        assert ServiceRequest.query.filter_by(guid=old.guid).one().status == 'active'


# ── FHIR _history / vread ─────────────────────────────────────────────────

class TestFhirHistory:
    def test_history_bundle_newest_first_and_vread_each(self, client, stubs):
        sr = _active()
        svc.archive_service_request(sr.guid, user_guid='u')
        r = client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history')
        assert r.status_code == 200
        b = r.get_json()
        assert (b['resourceType'], b['type'], b['total']) == ('Bundle', 'history', 3)
        assert [e['resource']['meta']['versionId'] for e in b['entry']] == ['3', '2', '1']
        v1 = client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/1').get_json()
        v2 = client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/2').get_json()
        v3 = client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/3')
        assert v3.headers['ETag'] == 'W/"3"'
        v3 = v3.get_json()
        assert (v1['status'], v2['status'], v3['status']) == ('draft', 'active', 'completed')
        assert v3['meta']['tag'] == [{'system': sr_journal.LOCAL_STATUS_SYSTEM, 'code': 'archived'}]
        for res in (v1, v2, v3):
            assert res['identifier'][0]['value'] == sr.guid
            _r5_valid(res)
        assert client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/9').status_code == 404

    def test_history_is_audited_as_a_read_of_the_patient(self, client, stubs):
        sr = _active()
        client.get(f'/api/v1/ServiceRequest/{sr.guid}/_history/1')
        row = AuditLog.query.filter_by(action='service_request.vread').one()
        assert row.data_subject_guid == PATIENT

    def test_care_plan_versions_render_as_valid_r5(self, stubs):
        sr = _create()
        cp = CarePlan.query.filter_by(guid=sr.care_plan_guid).one()
        cp.goals = [{'concept_name': 'Glukos', 'target_type': 'range'}]
        db.session.commit()
        for v in versioning.cp_versions(cp):
            _r5_valid(versioning.render_care_plan(v['ns'], v['version'], v['recorded_at']))

    def test_capability_advertises_vread_and_history(self, client):
        cs = client.get('/api/v1/metadata').get_json()
        (sr,) = [r for r in cs['rest'][0]['resource'] if r['type'] == 'ServiceRequest']
        codes = {i['code'] for i in sr['interaction']}
        assert {'vread', 'history-instance', 'patch'} <= codes
