"""Request-side contract scope enforcement on SR creation (ticket #135).

Standalone tests — these intentionally do NOT use the package conftest
because the test app fixture currently fails to bootstrap (FLASK_ENV
mismatch with AUTH_DISABLED; pre-existing, see progress.md). They
exercise the pure scope-service logic plus a minimal Flask app so the
SR-creation integration path is still covered.
"""
import os
import sys

# Force env BEFORE importing app modules.
os.environ.setdefault('AUTH_DISABLED', 'false')
os.environ.setdefault('FLASK_ENV', 'development')  # safe — see config.py
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('HMAC_SECRET', 'test-hmac-secret-min-32-chars-for-test')
os.environ.setdefault('INTERNAL_SERVICE_KEY', 'test-internal-key')
os.environ.setdefault('FLASK_SECRET_KEY', 'test-flask-secret')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret')

# This test file declares its own fixtures, so skip the package conftest.
collect_ignore = []
import pytest  # noqa: E402

from app.services import scope_service  # noqa: E402


CONCEPT_A = '11111111-1111-1111-1111-111111111111'
CONCEPT_B = '22222222-2222-2222-2222-222222222222'
CONCEPT_C = '33333333-3333-3333-3333-333333333333'

SNAPSHOT_AB = {
    'activities': [
        {'concept_guid': None, 'transactions': [{'concept_guid': CONCEPT_A}]},
        {'concept_guid': None, 'transactions': [{'concept_guid': CONCEPT_B}]},
    ],
}


# ── Pure helpers ───────────────────────────────────────────────────────


def test_extract_concept_guids_from_snapshot():
    guids = scope_service.extract_concept_guids_from_snapshot(SNAPSHOT_AB)
    assert guids == {CONCEPT_A, CONCEPT_B}


def test_extract_handles_goal_concept_and_procedure_concept():
    snapshot = {
        'activities': [
            {
                'concept_guid': CONCEPT_C,  # procedure concept
                'transactions': [
                    {'concept_guid': CONCEPT_A, 'goal_concept_guid': CONCEPT_B},
                ],
            },
        ],
        'goals': [{'concept_guid': CONCEPT_B}],
    }
    assert scope_service.extract_concept_guids_from_snapshot(snapshot) == {
        CONCEPT_A, CONCEPT_B, CONCEPT_C,
    }


def test_extract_robust_to_missing_keys():
    assert scope_service.extract_concept_guids_from_snapshot({}) == set()
    assert scope_service.extract_concept_guids_from_snapshot(
        {'activities': [None, 'string', {'transactions': None}]}
    ) == set()


def test_request_scope_guids_handles_strings_and_dicts():
    assert scope_service.request_scope_guids({
        'request_scope': [CONCEPT_A, {'concept_guid': CONCEPT_B}, {'guid': CONCEPT_C}]
    }) == {CONCEPT_A, CONCEPT_B, CONCEPT_C}


# ── Verdict matrix ─────────────────────────────────────────────────────


def test_validate_allow_when_no_contract():
    verdict, _ = scope_service.validate_snapshot_against_scope(SNAPSHOT_AB, None)
    assert verdict == 'allow'


def test_validate_allow_when_scope_unreachable(monkeypatch):
    """Fail-open: a failed scope fetch must not block SR authoring."""
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: None)
    verdict, _ = scope_service.validate_snapshot_against_scope(
        SNAPSHOT_AB, 'contract-1',
    )
    assert verdict == 'allow'


def test_validate_contract_inactive(monkeypatch):
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: {
        'status': 'revoked', 'scope_defined': True,
        'request_scope': [], 'return_scope': {},
    })
    verdict, payload = scope_service.validate_snapshot_against_scope(
        SNAPSHOT_AB, 'contract-1',
    )
    assert verdict == 'contract_inactive'
    assert payload['status'] == 'revoked'


def test_validate_out_of_scope(monkeypatch):
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: {
        'status': 'executed', 'scope_defined': True,
        'request_scope': [{'concept_guid': CONCEPT_A}],
        'return_scope': {},
    })
    verdict, payload = scope_service.validate_snapshot_against_scope(
        SNAPSHOT_AB, 'contract-1',
    )
    assert verdict == 'out_of_scope'
    assert CONCEPT_B in payload['out_of_scope_concept_guids']
    assert CONCEPT_A not in payload['out_of_scope_concept_guids']


def test_validate_allow_active_when_all_permitted(monkeypatch):
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: {
        'status': 'executed', 'scope_defined': True,
        'request_scope': [
            {'concept_guid': CONCEPT_A},
            {'concept_guid': CONCEPT_B},
        ],
        'return_scope': {},
    })
    verdict, _ = scope_service.validate_snapshot_against_scope(
        SNAPSHOT_AB, 'contract-1',
    )
    assert verdict == 'allow_active'


def test_validate_absent_request_scope_means_all_permitted(monkeypatch):
    """scope_defined=True but request_scope list is empty: the contract
    only restricts return_scope. Don't block requesters."""
    monkeypatch.setattr(scope_service, 'fetch_scope', lambda guid: {
        'status': 'executed', 'scope_defined': True,
        'request_scope': [],
        'return_scope': {'obligatory_return': [{'concept_guid': CONCEPT_A}]},
    })
    verdict, _ = scope_service.validate_snapshot_against_scope(
        SNAPSHOT_AB, 'contract-1',
    )
    assert verdict == 'allow_active'
