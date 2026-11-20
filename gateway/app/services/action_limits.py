"""Action limits on an order, with their provenance kept (operator, 2026-11-16).

Two different clinical things share the field names ``range_min/range_max``:

  * plan.pdhc's PlanDefinition carries the RECOMMENDED NORMAL range;
  * the ACTION limit -- when someone must act for THIS patient -- is set by
    the requester in request.pdhc, on the draft order's snapshot.

The snapshot starts as a copy of plan, and the requester may edit it while the
order is a draft. Before this module the edit replaced the snapshot wholesale
and the audit entry carried no details. So on a finalised order an action
limit a clinician chose and one inherited unchanged from plan's normal range
looked identical, and nothing said what had changed. Consumers that judge
values against these limits (dashboard.pdhc, MDR IIa) need to be able to say
which it is.

So every transaction with a range carries, alongside the unchanged
``range_min/range_max`` (the ACTION limit, which existing readers keep
reading):

  * ``recommended_range_min/max`` -- plan's value, frozen at create and owned by
    the SERVER: a client edit can never rewrite it;
  * ``action_limit_source`` -- ``plan_recommended`` while the action limit
    equals it, ``requester`` once a clinician has set something else.

Every edit is audited with the before/after of each changed action limit.
"""
from __future__ import annotations

import copy
import math

PLAN = "plan_recommended"
REQUESTER = "requester"


class InvalidActionLimit(ValueError):
    pass


def _transactions(snapshot):
    if not isinstance(snapshot, dict):
        return
    for act in snapshot.get("activities") or []:
        if isinstance(act, dict):
            for tx in act.get("transactions") or []:
                if isinstance(tx, dict):
                    yield tx


def _key(tx):
    return tx.get("transaction_guid") or tx.get("guid")


def _has_range(tx):
    return "range_min" in tx or "range_max" in tx


def _pair(tx):
    return (tx.get("range_min"), tx.get("range_max"))


def stamp_recommended(snapshot):
    """At create: the plan range is recorded as the recommendation."""
    out = copy.deepcopy(snapshot)
    for tx in _transactions(out):
        if _has_range(tx):
            tx["recommended_range_min"], tx["recommended_range_max"] = _pair(tx)
            tx["action_limit_source"] = PLAN
    return out


def _check(tx):
    lo, hi = _pair(tx)
    for v in (lo, hi):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
            raise InvalidActionLimit(f"limit {v!r} for {tx.get('concept_name') or _key(tx)} is not a number")
    if lo is not None and hi is not None and not lo < hi:
        raise InvalidActionLimit(f"action limit {lo}..{hi} for {tx.get('concept_name') or _key(tx)} needs min < max")


def _act_key(act):
    return act.get("activity_guid") or act.get("guid") or act.get("id")


def restore_transaction_guids(stored, edited):
    """Give back a measurement's transaction_guid that an edit dropped
    (2026-11-20). The order plan editor rebuilt each measurement from its form
    fields only, so a save lost transaction_guid -- the key gateway uses to
    link a delivered value to this order's measurement, and the key the
    action-limit provenance below is matched on.

    Restored only when unambiguous: same activity, same concept, and exactly
    one stored measurement of that concept there. A changed concept is a new
    measurement and gets nothing. Mutates ``edited``; returns the count.
    """
    if not isinstance(stored, dict) or not isinstance(edited, dict):
        return 0
    by_act = {}
    for act in stored.get("activities") or []:
        if isinstance(act, dict) and _act_key(act):
            by_act[_act_key(act)] = [t for t in act.get("transactions") or [] if isinstance(t, dict)]
    n = 0
    for act in edited.get("activities") or []:
        if not isinstance(act, dict):
            continue
        olds = by_act.get(_act_key(act)) or []
        for tx in act.get("transactions") or []:
            if not isinstance(tx, dict) or _key(tx) or not tx.get("concept_guid"):
                continue
            same = [o for o in olds if o.get("concept_guid") == tx["concept_guid"] and _key(o)]
            if len(same) == 1:
                tx["transaction_guid"] = _key(same[0])
                n += 1
    return n


def merge_edit(stored, edited):
    """The requester's edit, with server-owned provenance restored.

    Returns ``(snapshot_to_store, changes)``; ``changes`` lists every action
    limit that differs from the STORED one.
    """
    out = copy.deepcopy(edited)
    restore_transaction_guids(stored, out)
    before = {_key(tx): tx for tx in _transactions(stored) if _key(tx)}
    changes = []
    for tx in _transactions(out):
        for k in ("recommended_range_min", "recommended_range_max", "action_limit_source"):
            tx.pop(k, None)  # never the client's to set
        old = before.get(_key(tx))
        if old is not None and "recommended_range_min" in old:
            rec = (old.get("recommended_range_min"), old.get("recommended_range_max"))
        elif old is not None and _has_range(old):
            rec = _pair(old)  # a draft from before provenance existed
        else:
            rec = None
        if not _has_range(tx) and rec is None:
            continue
        _check(tx)
        if rec is not None:
            tx["recommended_range_min"], tx["recommended_range_max"] = rec
        tx["action_limit_source"] = PLAN if rec is not None and _pair(tx) == rec else REQUESTER
        prev = _pair(old) if old is not None else (None, None)
        if _pair(tx) != prev:
            changes.append({"transaction_guid": _key(tx), "concept_name": tx.get("concept_name"),
                            "before": list(prev), "after": list(_pair(tx)),
                            "recommended": list(rec) if rec else None})
    return out, changes


# ----------------------------------------------------------------- CarePlan goals
#
# A CarePlan's `goals` are the per-patient ACTION limits the dashboard judges
# values against first. They are copied from plan's PlanDefinition goals at
# create (plan's recommendation) and a clinician may change them. Same rule:
# the recommendation is frozen and server-owned, the source says whose the
# current value is, and every change is listed for the audit.

GOAL_FIELDS = ("target_type", "target_range_low", "target_range_high",
               "target_quantity", "target_operator", "target_unit")


def _goal_key(g, i):
    return g.get("guid") or g.get("goal_guid") or f"{g.get('concept_guid')}#{i}"


def _goal_value(g):
    return {k: g.get(k) for k in GOAL_FIELDS}


def _check_goal(g):
    lo, hi = g.get("target_range_low"), g.get("target_range_high")
    for v in (lo, hi, g.get("target_quantity")):
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)):
            raise InvalidActionLimit(f"goal value {v!r} for {g.get('concept_name') or g.get('concept_guid')} is not a number")
    if lo is not None and hi is not None and not lo < hi:
        raise InvalidActionLimit(f"goal range {lo}..{hi} for {g.get('concept_name') or g.get('concept_guid')} needs low < high")


def stamp_recommended_goals(goals, *, from_plan):
    """At create. Goals supplied by the requester are theirs, not plan's."""
    out = copy.deepcopy(goals or [])
    for g in out:
        if isinstance(g, dict):
            for k in ("recommended", "limit_source"):
                g.pop(k, None)
            if from_plan:
                g["recommended"] = _goal_value(g)
                g["limit_source"] = PLAN
            else:
                _check_goal(g)
                g["limit_source"] = REQUESTER
    return out


def merge_goals(stored, edited):
    """A goals edit with server-owned provenance restored; returns (goals, changes)."""
    before = {_goal_key(g, i): g for i, g in enumerate(stored or []) if isinstance(g, dict)}
    out = copy.deepcopy(edited or [])
    changes = []
    seen = set()
    for i, g in enumerate(out):
        if not isinstance(g, dict):
            continue
        for k in ("recommended", "limit_source"):
            g.pop(k, None)
        _check_goal(g)
        key = _goal_key(g, i)
        seen.add(key)
        old = before.get(key)
        rec = old.get("recommended") if old else None
        if rec is not None:
            g["recommended"] = rec
        g["limit_source"] = PLAN if rec is not None and _goal_value(g) == rec else REQUESTER
        prev = _goal_value(old) if old else None
        if prev != _goal_value(g):
            changes.append({"goal": key, "concept_guid": g.get("concept_guid"),
                            "before": prev, "after": _goal_value(g), "recommended": rec})
    for key, old in before.items():
        if key not in seen:
            changes.append({"goal": key, "concept_guid": old.get("concept_guid"),
                            "before": _goal_value(old), "after": None, "recommended": old.get("recommended")})
    return out, changes
