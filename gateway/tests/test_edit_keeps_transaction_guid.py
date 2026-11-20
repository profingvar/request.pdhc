"""2026-11-20 — editing a draft order's plan must not drop transaction_guid.

The order plan editor rebuilt each measurement from its form fields only, so
a save lost transaction_guid: the key gateway links a delivered value to the
order's measurement by, and the key action-limit provenance is matched on.
Fixed twice: the editor keeps the loaded fields, and the server restores a
dropped key when it is unambiguous.
"""
from app.services.action_limits import PLAN, merge_edit, restore_transaction_guids


def _snap(*txs, act="a1"):
    return {"activities": [{"guid": act, "title": "CGM", "transactions": list(txs)}]}


STORED = _snap({"transaction_guid": "tx-1", "concept_guid": "c1", "concept_name": "B-glucos",
                "range_min": 3, "range_max": 10},
               {"transaction_guid": "tx-2", "concept_guid": "c2", "concept_name": "CGM"})


def test_a_dropped_guid_is_restored_from_the_same_activity_and_concept():
    edited = _snap({"concept_guid": "c1", "range_min": 3, "range_max": 10},
                   {"concept_guid": "c2"})
    out, _ = merge_edit(STORED, edited)
    assert [t["transaction_guid"] for t in out["activities"][0]["transactions"]] == ["tx-1", "tx-2"]


def test_provenance_survives_because_the_key_does():
    edited = _snap({"concept_guid": "c1", "range_min": 3, "range_max": 10}, {"concept_guid": "c2"})
    out, changes = merge_edit(STORED, edited)
    tx = out["activities"][0]["transactions"][0]
    assert tx["action_limit_source"] == PLAN and changes == []


def test_a_changed_concept_is_a_new_measurement():
    edited = _snap({"concept_guid": "c9"}, {"concept_guid": "c2"})
    out, _ = merge_edit(STORED, edited)
    assert "transaction_guid" not in out["activities"][0]["transactions"][0]


def test_another_activity_gets_nothing():
    edited = _snap({"concept_guid": "c1"}, act="other")
    assert restore_transaction_guids(STORED, edited) == 0


def test_ambiguous_is_left_alone():
    stored = _snap({"transaction_guid": "tx-1", "concept_guid": "c1"},
                   {"transaction_guid": "tx-3", "concept_guid": "c1"})
    edited = _snap({"concept_guid": "c1"})
    assert restore_transaction_guids(stored, edited) == 0


def test_a_kept_guid_is_never_overwritten():
    edited = _snap({"transaction_guid": "tx-own", "concept_guid": "c1"})
    restore_transaction_guids(STORED, edited)
    assert edited["activities"][0]["transactions"][0]["transaction_guid"] == "tx-own"
