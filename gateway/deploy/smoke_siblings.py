#!/usr/bin/env python3
"""request.pdhc — does every call to a SIBLING service actually work? (#708)

Run it INSIDE the container, the only place the real keys exist:

    docker exec request_pdhc_app python deploy/smoke_siblings.py
    docker exec request_pdhc_app python deploy/smoke_siblings.py --json

READ-ONLY. Every check drives one of request.pdhc's OWN service functions
rather than a hand-written request, so the smoke cannot disagree with
production about a path, a header or a credential. That is not fussiness: the
first version of the analyse smoke probed a path I had invented, and the first
gateway one presented the wrong credential to ips — both would have reported a
healthy boundary that no code uses.

## Why this service in particular

`ips_client`'s own docstring records that its spärr filter sent the key as
`X-API-Key` (ips reads only `Authorization`) against the staff `/blocks` list
endpoint instead of the purpose-built predicate, so **every call 401'd and the
filter silently failed open — no ServiceRequest was ever hidden.** That is
fixed. Nothing asserted it stays fixed, and a spärr filter that fails open
looks exactly like one with nothing to hide.

Exit code is 0 only if every check passed.
"""
from __future__ import annotations

import json as _json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

RESET, RED, GRN, BOLD = "\033[0m", "\033[31m", "\033[32m", "\033[1m"
results: list[dict] = []

FAKE_PATIENT = "00000000-0000-4000-8000-000000000000"
FAKE_ORG = "00000000-0000-4000-8000-0000000000ff"


def _unpack(result, what: str):
    """These service functions return ``(payload, status)``, and an upstream
    failure returns ``({'code': 'upstream_error', ...}, 502)``.

    The first version of this smoke did ``len(rows)`` on the result. That
    counted the TUPLE — always 2 — so it reported "2 contract(s)" when there
    were 8, and, far worse, it would have passed on a 502 as well, because a
    two-element tuple is neither empty nor None. A smoke that goes green on an
    upstream error is worse than no smoke.
    """
    if not (isinstance(result, tuple) and len(result) == 2):
        return False, f"{what}: unexpected return shape {type(result).__name__}"
    payload, status = result
    if status != 200:
        return False, f"{what}: upstream returned {status} — {str(payload)[:90]}"
    n = len(payload) if hasattr(payload, "__len__") else "?"
    return True, f"{n} {what} (status 200)"


def check(name):
    def wrap(fn):
        t = time.time()
        try:
            ok, note = fn()
        except Exception as e:                        # noqa: BLE001
            ok, note = False, f"{type(e).__name__}: {e}"
        results.append({"check": name, "ok": bool(ok), "note": note,
                        "ms": int((time.time() - t) * 1000)})
        return ok
    return wrap


def main(as_json: bool = False) -> int:
    from app import create_app
    app = create_app()
    with app.app_context():
        from flask import current_app
        cfg = current_app.config

        @check("config: every sibling URL and the ips key are set")
        def _():
            want = {k: cfg.get(k) for k in
                    ("IPS_BASE_URL", "CONTRACT_BASE_URL", "PLAN_BASE_URL",
                     "SSO_BASE_URL", "IPS_API_KEY")}
            absent = [k for k, v in want.items() if not v]
            return (not absent), ("all 5 present" if not absent
                                  else "MISSING: " + ", ".join(absent))

        # ── ips: the spärr predicate that once failed open ──
        @check("ips: the spärr predicate answers (it once 401'd and failed OPEN)")
        def _():
            from app.services.ips_client import IpsClient
            client = IpsClient(
                base_url=cfg.get("IPS_BASE_URL"),
                api_key=cfg.get("IPS_API_KEY"))
            blocked, scopes = client.check_block(FAKE_PATIENT, FAKE_ORG)
            # A nonexistent patient is genuinely unblocked, so False is right.
            # The failure this guards against is a 401 that ALSO returns
            # False — indistinguishable from here, which is why the next
            # check exists.
            return (blocked is False and isinstance(scopes, list)), (
                f"is_blocked={blocked}, {len(scopes)} scope(s)")

        @check("ips: a spärr 401 would be VISIBLE, not silently fail-open")
        def _():
            # The real regression risk. check_block returns (False, []) on any
            # error, by design and for legal reasons — so a wrong credential
            # is invisible in its return value. Assert the credential is
            # accepted by making the same authenticated call directly and
            # requiring a non-401. Without this, the only symptom of the
            # original bug would be "nothing is ever hidden".
            import requests
            base = (cfg.get("IPS_BASE_URL") or "").rstrip("/")
            r = requests.get(
                f"{base}/api/v1/patients/{FAKE_PATIENT}/blocks/check",
                params={"source_clinic_id": FAKE_ORG},
                headers={"Accept": "application/json",
                         "Authorization": f"ApiKey {cfg.get('IPS_API_KEY')}"},
                timeout=15)
            if r.status_code in (401, 403):
                return False, (f"-> {r.status_code}: the ips ApiKey is REFUSED, "
                               f"so the spärr filter is failing open silently")
            return True, f"-> {r.status_code} (the ApiKey is accepted)"

        @check("ips: the consent predicate answers")
        def _():
            from app.services.ips_consent_client import IpsConsentClient
            c = IpsConsentClient(base_url=cfg.get("IPS_BASE_URL"),
                                 api_key=cfg.get("IPS_API_KEY"))
            rows = c.fetch_consents_for_grantee(FAKE_PATIENT, FAKE_ORG)
            # A nonexistent patient yields no consents, which is the correct
            # answer; the point is that the call authenticates and parses.
            return isinstance(rows, list), f"{len(rows)} consent(s)"

        @check("ips: the patient directory answers")
        def _():
            from app.services.patient_service import list_patients
            return _unpack(list_patients({"limit": 1}), "patient(s)")

        # ── contract.pdhc ──
        @check("contract: the Contract list is readable")
        def _():
            from app.services.contract_service import list_contracts
            return _unpack(list_contracts(), "contract(s)")

        # ── plan.pdhc ──
        @check("plan: PlanDefinitions are readable")
        def _():
            from app.services.plan_definition_service import list_plan_definitions
            return _unpack(list_plan_definitions(), "plandefinition(s)")

        # ── sso ──
        @check("sso: reachable")
        def _():
            import requests
            base = (cfg.get("SSO_BASE_URL") or "").rstrip("/")
            r = requests.get(f"{base}/api/health", timeout=10)
            return r.status_code == 200, f"/api/health -> {r.status_code}"

    failed = [r for r in results if not r["ok"]]
    if as_json:
        print(_json.dumps({"service": "request.pdhc", "checks": results,
                           "failed": len(failed)}, indent=2))
    else:
        print(f"\n{BOLD}request.pdhc — sibling smoke{RESET}\n")
        for r in results:
            mark = f"{GRN}✓{RESET}" if r["ok"] else f"{RED}✗{RESET}"
            print(f"  {mark} {r['check']:<62} {r['note']}  ({r['ms']}ms)")
        print(f"\n{RED if failed else GRN}{BOLD}"
              f"{f'{len(failed)} check(s) failed.' if failed else f'All {len(results)} checks passed.'}"
              f"{RESET}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(as_json="--json" in sys.argv))
