"""Ticket #583 — the request must carry each concept's FULL definition.

plan.pdhc holds ``response_type`` and ``unit`` on the *concept*, not on the
transaction, so a captured PlanDefinition snapshot historically carried
neither and every consumer had to call plan.pdhc back to interpret an
observation. Two consequences: the stored request could not be read without a
live plan.pdhc, and editing a concept later silently changed how an already
captured request was interpreted.

``enrich_snapshot_concepts`` stamps the definition into the snapshot at
capture time, and ``_infer_response_type`` now prefers what the snapshot
carries over the live lookup.
"""
from unittest.mock import patch

from app.services import context_service as cs


FEV1 = "6521528c-db59-45c5-a492-003c28f27623"
DIARY = "11111111-2222-3333-4444-555555555555"


def _snapshot(*txs):
    return {"goals": [], "activities": [{"transactions": list(txs)}]}


def _maps(rt=None, rt_name=None, unit=None):
    """Patch the three plan.pdhc-derived maps."""
    return (
        patch.object(cs, "_plan_concept_response_types", return_value=rt or {}),
        patch.object(cs, "_plan_concept_response_type_names",
                     return_value=rt_name or {}),
        patch.object(cs, "_plan_concept_units", return_value=unit or {}),
    )


class TestEnrichment:

    def test_stamps_response_type_name_and_unit(self):
        snap = _snapshot({"concept_guid": FEV1, "concept_name": "FEV1"})
        a, b, c = _maps(rt={FEV1: "numeric"},
                        rt_name={FEV1: "Numerical"},
                        unit={FEV1: "L"})
        with a, b, c:
            cs.enrich_snapshot_concepts(snap)
        tx = snap["activities"][0]["transactions"][0]
        assert tx["response_type"] == "numeric"
        assert tx["response_type_name"] == "Numerical"   # what #583 asks for
        assert tx["unit"] == "L"

    def test_does_not_overwrite_what_the_snapshot_already_has(self):
        # Once captured, the request is authoritative over plan.pdhc.
        snap = _snapshot({"concept_guid": FEV1, "response_type": "text",
                          "response_type_name": "Free text", "unit": "mL"})
        a, b, c = _maps(rt={FEV1: "numeric"},
                        rt_name={FEV1: "Numerical"},
                        unit={FEV1: "L"})
        with a, b, c:
            cs.enrich_snapshot_concepts(snap)
        tx = snap["activities"][0]["transactions"][0]
        assert tx["response_type"] == "text"
        assert tx["response_type_name"] == "Free text"
        assert tx["unit"] == "mL"

    def test_enriches_every_transaction_across_activities(self):
        snap = {"activities": [
            {"transactions": [{"concept_guid": FEV1}]},
            {"transactions": [{"concept_guid": DIARY}]},
        ]}
        a, b, c = _maps(rt={FEV1: "numeric", DIARY: "categorical"},
                        rt_name={FEV1: "Numerical", DIARY: "Single choice"})
        with a, b, c:
            cs.enrich_snapshot_concepts(snap)
        assert snap["activities"][0]["transactions"][0]["response_type_name"] == "Numerical"
        assert snap["activities"][1]["transactions"][0]["response_type_name"] == "Single choice"

    def test_plan_unreachable_is_a_no_op_not_an_error(self):
        snap = _snapshot({"concept_guid": FEV1})
        a, b, c = _maps()          # every map empty, as when plan.pdhc is down
        with a, b, c:
            out = cs.enrich_snapshot_concepts(snap)
        assert out is snap
        assert "response_type" not in snap["activities"][0]["transactions"][0]

    def test_tolerates_junk_shapes(self):
        assert cs.enrich_snapshot_concepts(None) is None
        assert cs.enrich_snapshot_concepts({}) == {}
        snap = {"activities": [None, {"transactions": [None, "nonsense"]}]}
        a, b, c = _maps(rt={FEV1: "numeric"})
        with a, b, c:
            cs.enrich_snapshot_concepts(snap)   # must not raise

    def test_transaction_without_concept_guid_is_skipped(self):
        snap = _snapshot({"concept_name": "orphan"})
        a, b, c = _maps(rt={FEV1: "numeric"}, rt_name={FEV1: "Numerical"})
        with a, b, c:
            cs.enrich_snapshot_concepts(snap)
        assert "response_type" not in snap["activities"][0]["transactions"][0]


class TestSnapshotBeatsLiveLookup:

    def test_infer_prefers_the_snapshots_own_response_type(self):
        # plan.pdhc now says categorical; the captured request said numeric.
        # The captured request wins — interpretation must not drift.
        tx = {"concept_guid": FEV1, "response_type": "numeric"}
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "categorical"}):
            assert cs._infer_response_type(tx) == "numeric"

    def test_unrecognised_snapshot_value_falls_through_to_plan(self):
        tx = {"concept_guid": FEV1, "response_type": "wat"}
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "numeric"}):
            assert cs._infer_response_type(tx) == "numeric"

    def test_old_snapshot_without_response_type_still_uses_plan(self):
        tx = {"concept_guid": FEV1}
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "numeric"}):
            assert cs._infer_response_type(tx) == "numeric"


class TestExtractedTransactionCarriesTheName:

    def test_response_type_name_reaches_the_gateway_context(self):
        snap = _snapshot({"guid": "tx-1", "concept_guid": FEV1,
                          "concept_name": "FEV1",
                          "response_type": "numeric",
                          "response_type_name": "Numerical"})
        a, b, c = _maps()
        with a, b, c:
            txs = cs._extract_transactions(snap)
        assert len(txs) == 1
        assert txs[0]["response_type"] == "numeric"
        assert txs[0]["response_type_name"] == "Numerical"

    def test_name_resolved_live_for_an_unenriched_snapshot(self):
        snap = _snapshot({"guid": "tx-1", "concept_guid": FEV1})
        a, b, c = _maps(rt={FEV1: "numeric"}, rt_name={FEV1: "Numerical"})
        with a, b, c:
            txs = cs._extract_transactions(snap)
        assert txs[0]["response_type_name"] == "Numerical"
