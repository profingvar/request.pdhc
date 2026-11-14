"""Access-model reform scope helpers (M0 #419).

Config-free (no app imports) so they unit-test without the Flask bootstrap.

The reform blob carries ``affiliations[]`` where each entry pairs
``care_unit_guid`` with ``care_unit_name``. That pairing finally fills the
long-standing ``organization_names`` GAP (the legacy blob shipped
``organization_ids`` and ``organization_names`` as *parallel arrays* that were
frequently mismatched or empty).

THE MIGRATION WINDOW IS CLOSED (2026-11-14). Both helpers used to fall back
to the legacy ``organization_ids`` when a caller had no affiliation. That
fallback is gone: under the main rule (operator 2026-11-13) a person sees
patients through the CARE UNITS they are AFFILIATED to, and nothing else.
``organization_ids`` is SSO's list of old memberships — a membership was never
a care-unit assignment, and it could name a vårdgivare. Removed once SSO's
employment backfill and the 2026-11-14 decisions left every professional with
at least one affiliation, so nobody lost access by it. No affiliation now
means no scope: absence narrows, never widens.
"""


def caller_org_ids(blob):
    """Zone-1 read scope: ``affiliations[].care_unit_guid``, and ONLY that.
    Zone-2 (parent care org) is deliberately NOT folded in here, and the
    legacy ``organization_ids`` is no longer read (see the module note)."""
    affs = (blob or {}).get("affiliations") or []
    return [a["care_unit_guid"] for a in affs if a.get("care_unit_guid")]


def caller_org_names(blob):
    """Map ``care_unit_guid -> care_unit_name`` for the caller (M0 #419 — fills
    the organization_names gap). From ``affiliations[]`` the guid and name come
    from the same entry, so they can never be mismatched. No legacy fallback."""
    affs = (blob or {}).get("affiliations") or []
    return {a["care_unit_guid"]: a.get("care_unit_name")
            for a in affs if a.get("care_unit_guid")}
