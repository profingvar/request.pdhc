"""2026-11-19 (MMD_plan): a goal linkage is trusted only when the goal concept
has the transaction's unit. MMD_plan linked its one goal (cgm_mean_glucose,
mmol/L) to every activity, and gateway labels a value with its goal concept,
so sleep, blood pressure, anxiety and stress were stored as glucose."""
from unittest.mock import patch

from app.services import context_service as cs

GLUC, CGM, SLEEP, SYS, ANX = "g-gluc", "c-cgm", "c-sleep", "c-sys", "c-anx"
UNITS = {GLUC: "mmol/L", CGM: "mmol/L", SLEEP: "h", SYS: "mmHg"}
SNAP = {"goals": [{"guid": "goal-1", "concept_guid": GLUC, "concept_name": "cgm_mean_glucose"}],
        "activities": [
            {"title": "CGM", "goal_concept_guid": GLUC, "transactions": [{"guid": "t-cgm", "concept_guid": CGM}]},
            {"title": "Sleep", "goal_concept_guid": GLUC, "transactions": [{"guid": "t-sleep", "concept_guid": SLEEP}]},
            {"title": "Vecka", "transactions": [{"guid": "t-sys", "concept_guid": SYS},
                                                {"guid": "t-anx", "concept_guid": ANX}]},
        ]}


def _goals():
    with patch.object(cs, "_plan_concept_units", return_value=UNITS), \
            patch.object(cs, "_plan_concept_response_types", return_value={}, create=True):
        return {t["transaction_guid"]: t["goal_concept_guid"] for t in cs._extract_transactions(SNAP)}


def test_same_unit_keeps_the_goal():
    assert _goals()["t-cgm"] == GLUC


def test_another_unit_or_no_unit_drops_the_goal():
    g = _goals()
    assert g["t-sleep"] is None and g["t-sys"] is None and g["t-anx"] is None
