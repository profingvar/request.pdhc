"""Access-model reform scope helpers (M0 #419).

Config-free (no app imports) so they unit-test without the Flask bootstrap.

The reform blob carries ``affiliations[]`` where each entry pairs
``care_unit_guid`` with ``care_unit_name``. That pairing finally fills the
long-standing ``organization_names`` GAP (the legacy blob shipped
``organization_ids`` and ``organization_names`` as *parallel arrays* that were
frequently mismatched or empty). Both helpers dual-read: affiliations[] first,
then the legacy parallel arrays during the migration window.
"""


def caller_org_ids(blob):
    """Zone-1 read scope: ``affiliations[].care_unit_guid`` — the exact
    equivalent of the legacy flat ``organization_ids`` semantics — with a
    dual-read fallback to ``organization_ids``. Zone-2 (parent care org) is
    deliberately NOT folded in here."""
    affs = (blob or {}).get("affiliations") or []
    if affs:
        return [a["care_unit_guid"] for a in affs if a.get("care_unit_guid")]
    return list((blob or {}).get("organization_ids") or [])


def caller_org_names(blob):
    """Map ``care_unit_guid -> care_unit_name`` for the caller (M0 #419 — fills
    the organization_names gap). From ``affiliations[]`` the guid and name come
    from the same entry, so they can never be mismatched. Dual-read fallback to
    the legacy parallel ``organization_ids`` / ``organization_names`` arrays
    (index-aligned; missing names -> None)."""
    affs = (blob or {}).get("affiliations") or []
    if affs:
        return {a["care_unit_guid"]: a.get("care_unit_name")
                for a in affs if a.get("care_unit_guid")}
    ids = list((blob or {}).get("organization_ids") or [])
    names = list((blob or {}).get("organization_names") or [])
    return {g: (names[i] if i < len(names) else None)
            for i, g in enumerate(ids)}
