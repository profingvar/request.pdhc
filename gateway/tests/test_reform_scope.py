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


def test_legacy_organization_ids_ALONE_grant_nothing():
    """2026-11-14: the fallback is gone. These two tests used to PIN it
    (organization_ids -> scope). A membership is not a care-unit assignment,
    so a blob with memberships and no affiliation has no scope at all."""
    blob = {"organization_ids": ["o1", "o2"],
            "organization_names": ["Org One", "Org Two"]}
    assert caller_org_ids(blob) == []
    assert caller_org_names(blob) == {}


def test_an_EMPTY_affiliation_list_does_not_fall_back():
    blob = {"affiliations": [], "organization_ids": ["o1"]}
    assert caller_org_ids(blob) == []


def test_empty_and_none():
    assert caller_org_ids({}) == []
    assert caller_org_ids(None) == []
    assert caller_org_names(None) == {}
