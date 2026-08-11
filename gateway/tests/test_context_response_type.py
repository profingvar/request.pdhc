"""Regression: numeric concepts (FEV1, spo2, peak-flow) must resolve to the
gateway 'numeric' response_type, not 'text'.

The SR snapshot drops the concept's unit + response_type, so the old
shape-only heuristic returned 'text' for FEV1 (no range/unit/expected) and the
gateway ObservationValidator 422'd every numeric provider reading. The fix
resolves the concept's real response_type from plan.pdhc (the authority),
mapping plan vocab -> gateway vocab, with the heuristic as fallback.
"""
from unittest.mock import patch

from app.services import context_service as cs


FEV1 = "6521528c-db59-45c5-a492-003c28f27623"


def _tx(**over):
    t = {"concept_guid": FEV1, "range_min": None, "range_max": None,
         "expected_value": None, "unit": None}
    t.update(over)
    return t


class TestPlanAuthoritative:
    def test_numeric_concept_resolves_numeric_even_without_shape_hints(self):
        # FEV1: no range, no unit, no expected_value in the lossy snapshot.
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "numeric"}):
            assert cs._infer_response_type(_tx()) == "numeric"

    def test_boolean_concept_resolves_boolean(self):
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "boolean"}):
            assert cs._infer_response_type(_tx()) == "boolean"

    def test_categorical_concept_resolves_categorical(self):
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "categorical"}):
            assert cs._infer_response_type(_tx()) == "categorical"


class TestHeuristicFallback:
    def test_falls_back_to_range_when_plan_unresolved(self):
        with patch.object(cs, "_plan_concept_response_types", return_value={}):
            assert cs._infer_response_type(_tx(range_min=0, range_max=900)) == "numeric"

    def test_falls_back_to_unit_when_plan_unresolved(self):
        with patch.object(cs, "_plan_concept_response_types", return_value={}):
            assert cs._infer_response_type(_tx(unit="L/min")) == "numeric"

    def test_falls_back_to_text_when_no_signal(self):
        with patch.object(cs, "_plan_concept_response_types", return_value={}):
            assert cs._infer_response_type(_tx()) == "text"

    def test_plan_resolution_wins_over_heuristic(self):
        # Even a categorical concept that happens to carry a range must follow
        # plan.pdhc, not the range heuristic.
        with patch.object(cs, "_plan_concept_response_types",
                          return_value={FEV1: "categorical"}):
            assert cs._infer_response_type(_tx(range_min=1, range_max=5)) == "categorical"


class TestUnitResolution:
    def test_extract_transactions_resolves_unit_from_plan(self):
        # #559: snapshot drops unit; resolve it (and response_type) from plan.
        snapshot = {"goals": [], "activities": [
            {"transactions": [{"guid": "t1", "concept_guid": FEV1}]}]}
        with patch.object(cs, "_plan_concept_units", return_value={FEV1: "L"}), \
             patch.object(cs, "_plan_concept_response_types", return_value={FEV1: "numeric"}):
            txns = cs._extract_transactions(snapshot)
        assert txns[0]["unit"] == "L"
        assert txns[0]["response_type"] == "numeric"

    def test_snapshot_unit_wins_over_plan(self):
        snapshot = {"goals": [], "activities": [
            {"transactions": [{"guid": "t1", "concept_guid": FEV1, "unit": "mL"}]}]}
        with patch.object(cs, "_plan_concept_units", return_value={FEV1: "L"}), \
             patch.object(cs, "_plan_concept_response_types", return_value={}):
            txns = cs._extract_transactions(snapshot)
        assert txns[0]["unit"] == "mL"


class TestVocabMap:
    def test_all_plan_types_map(self):
        m = cs._PLAN_RT_TO_GATEWAY
        assert m["numerical"] == "numeric"
        assert m["integer"] == "numeric"
        assert m["slider"] == "numeric"
        assert m["boolean"] == "boolean"
        assert m["single choice"] == "categorical"
        assert m["multiple choice"] == "categorical"
        assert m["free text"] == "text"
