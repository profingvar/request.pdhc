"""M0 #419 — request adopts affiliations[] scope + fills the organization_names gap.

The reform blob's affiliations[] pair care_unit_guid with care_unit_name, so
the caller's org name map can never be mismatched (the legacy parallel
organization_ids/organization_names arrays were frequently empty/misaligned).
"""
from app.services.reform_scope import caller_org_ids, caller_org_names


def test_ids_from_affiliations():
    blob = {"affiliations": [
        {"care_unit_guid": "u1", "care_unit_name": "Vårdcentral A"},
        {"care_unit_guid": "u2", "care_unit_name": "Vårdcentral B"}]}
    assert caller_org_ids(blob) == ["u1", "u2"]


def test_names_paired_from_affiliations():
    blob = {"affiliations": [
        {"care_unit_guid": "u1", "care_unit_name": "Vårdcentral A"},
        {"care_unit_guid": "u2", "care_unit_name": "Vårdcentral B"}]}
    assert caller_org_names(blob) == {"u1": "Vårdcentral A", "u2": "Vårdcentral B"}


def test_ids_precedence_over_legacy():
    blob = {"affiliations": [{"care_unit_guid": "u1"}],
            "organization_ids": ["other"]}
    assert caller_org_ids(blob) == ["u1"]


def test_legacy_parallel_array_fallback():
    blob = {"organization_ids": ["o1", "o2"],
            "organization_names": ["Org One", "Org Two"]}
    assert caller_org_ids(blob) == ["o1", "o2"]
    assert caller_org_names(blob) == {"o1": "Org One", "o2": "Org Two"}


def test_legacy_names_gap_yields_none():
    # The GAP: organization_names shorter/empty -> None, never an IndexError.
    blob = {"organization_ids": ["o1", "o2"], "organization_names": ["Org One"]}
    assert caller_org_names(blob) == {"o1": "Org One", "o2": None}


def test_empty_and_none():
    assert caller_org_ids({}) == []
    assert caller_org_ids(None) == []
    assert caller_org_names(None) == {}
