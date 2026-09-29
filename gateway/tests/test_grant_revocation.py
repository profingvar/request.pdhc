"""#708 — a grant could be issued and used, but never withdrawn.

`DataExchangeGrant.is_valid()` and `validate_grant_detailed` have always
honoured the `revoked` flag. `revoke_grant` was the only thing that could
set it, and nothing called `revoke_grant` — so the check was live, the
consequence was enforced, and the switch was not connected to anything.

Found by the #704 triage. The report first called it "redundant, the CLI
already revokes"; the CLI revokes PATs and webhook secrets, which are
different objects. It was not redundant, it was the whole withdrawal path.
"""
import uuid

import pytest

from app.models.security_models import DataExchangeGrant
from app.services.audit_service import AuditLog
from app.services.grant_service import (
    issue_grant, revoke_grant, validate_grant,
)


def _issue(app):
    with app.app_context():
        sr, pat, org, con = (str(uuid.uuid4()) for _ in range(4))
        data, status = issue_grant(
            service_request_guid=sr, patient_guid=pat,
            provider_org_guid=org, contract_guid=con,
        )
        assert status == 201, data
        return data, (sr, pat, org, con)


class TestWithdrawingAGrant:

    def test_a_revoked_grant_stops_validating(self, app):
        """The point of the whole exercise: before #708 this could not be
        reached, so a grant stood until expires_at whatever happened."""
        data, (sr, pat, org, con) = _issue(app)
        with app.app_context():
            assert validate_grant(sr, pat, org, con,
                                  data['grant_token']) is not None
            _, status = revoke_grant(data['guid'], user_guid='test')
            assert status == 200
            assert validate_grant(sr, pat, org, con,
                                  data['grant_token']) is None

    def test_it_writes_an_audit_event(self, app):
        """A withdrawal that leaves no trace is not a withdrawal anyone can
        later prove happened — and this one carries data_subject_guid, so a
        patient's uses and their revocation come out of one query."""
        data, (sr, pat, org, con) = _issue(app)
        with app.app_context():
            revoke_grant(data['guid'], user_guid='operator-1')
            ev = (AuditLog.query
                  .filter_by(action='grant.revoked',
                             resource_guid=data['guid'])
                  .first())
            assert ev is not None
            assert ev.user_guid == 'operator-1'
            assert ev.details['data_subject_guid'] == pat
            assert ev.details['provider_org_guid'] == org

    def test_revoking_twice_is_refused_not_silently_repeated(self, app):
        """Same contract as revoke_pat: a second call is a 400, so a script
        that loops cannot report success for work it did not do."""
        data, _ = _issue(app)
        with app.app_context():
            assert revoke_grant(data['guid'])[1] == 200
            body, status = revoke_grant(data['guid'])
            assert status == 400
            assert body['code'] == 'already_revoked'

    def test_an_unknown_guid_is_a_404(self, app):
        with app.app_context():
            body, status = revoke_grant(str(uuid.uuid4()))
            assert status == 404
            assert body['code'] == 'not_found'

    def test_it_returns_the_grant_not_a_model_object(self, app):
        """The old version returned the ORM row (or None), which is why no
        caller could tell 'not found' from 'done'."""
        data, _ = _issue(app)
        with app.app_context():
            body, status = revoke_grant(data['guid'])
            assert isinstance(body, dict)
            assert body['guid'] == data['guid']
            assert body['revoked'] is True

    def test_only_the_named_grant_is_touched(self, app):
        a, _ = _issue(app)
        b, _ = _issue(app)
        with app.app_context():
            revoke_grant(a['guid'])
            other = DataExchangeGrant.query.filter_by(guid=b['guid']).first()
            assert other.revoked is False


class TestTheCliCommand:

    def test_it_revokes_and_names_what_it_revoked(self, app, runner):
        data, _ = _issue(app)
        res = runner.invoke(args=['provider', 'revoke-grant',
                                  '--grant-guid', data['guid']])
        assert res.exit_code == 0, res.output
        assert data['guid'] in res.output
        with app.app_context():
            row = DataExchangeGrant.query.filter_by(guid=data['guid']).first()
            assert row.revoked is True

    def test_an_unknown_guid_exits_nonzero(self, app, runner):
        """An operator revoking the wrong guid must not get a clean exit."""
        res = runner.invoke(args=['provider', 'revoke-grant',
                                  '--grant-guid', str(uuid.uuid4())])
        assert res.exit_code != 0
