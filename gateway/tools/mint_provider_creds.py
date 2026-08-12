#!/usr/bin/env python3
"""Mint the two provider credentials for an onboarding — a PAT and a fresh
grant token — and print them for out-of-band handover.

Run inside the request.pdhc app container (it needs the app + DB):

    docker exec -e PYTHONPATH=/app -it request_pdhc_app \
        python tools/mint_provider_creds.py

Defaults target the UAS <-> Medituner AB asthma home-monitoring onboarding;
pass --org-guid/--contract-guid/--sr-guid/--patient-guid to reuse it for any
provider. Run WITHOUT args to regenerate the Medituner keys.

Effect (both are state-changing — the raw values print ONCE):
  * PAT  — a brand-new Provider Access Token (X-Provider-Token header).
  * grant — REVOKES any existing non-revoked grant for this SR+org+contract,
            then issues a fresh one (body `grant_token`).

Hand the two values to the provider on TWO SEPARATE channels — never together.
"""
import argparse
import sys

from app import create_app, db
from app.services.pat_service import issue_pat
from app.services import grant_service
from app.models.security_models import DataExchangeGrant

# UAS <-> Medituner AB, asthma home-monitoring (defaults).
DEFAULTS = {
    "org_guid": "7a69ab02-dfce-43ae-ade7-fabf6b858d84",       # MeditunerAB
    "contract_guid": "b23c8bec-b0f5-4acc-86f8-090fa075a234",  # executed contract
    "sr_guid": "4b8598b0-d857-4ba5-bc66-925972206cba",        # active ServiceRequest
    "patient_guid": "612a2995-f95a-4efb-8f6e-e203d339ac5a",
}


def main():
    ap = argparse.ArgumentParser(description="Mint provider PAT + fresh grant.")
    ap.add_argument("--org-guid", default=DEFAULTS["org_guid"])
    ap.add_argument("--contract-guid", default=DEFAULTS["contract_guid"])
    ap.add_argument("--sr-guid", default=DEFAULTS["sr_guid"])
    ap.add_argument("--patient-guid", default=DEFAULTS["patient_guid"])
    ap.add_argument("--expires-days", type=int, default=90)
    ap.add_argument("--scopes", default="read,write")
    ap.add_argument("--delivery-mode", choices=["poll", "push"], default="poll")
    ap.add_argument("--push-endpoint-url", default=None,
                    help="required if --delivery-mode push")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        # 1. PAT -------------------------------------------------------------
        pat, st = issue_pat(
            provider_org_guid=args.org_guid,
            contract_guid=args.contract_guid,
            scopes=args.scopes,
            delivery_mode=args.delivery_mode,
            push_endpoint_url=args.push_endpoint_url,
            expires_days=args.expires_days,
            created_by_user_guid="mint-script",
        )
        if st != 201:
            print(f"ERROR issuing PAT ({st}): {pat}", file=sys.stderr)
            return 1
        pat_guid, pat_raw = pat["guid"], pat["raw_token"]

        # 2. Fresh grant — revoke any live one first, then issue -------------
        revoked = 0
        for g in DataExchangeGrant.query.filter_by(
                service_request_guid=args.sr_guid,
                provider_org_guid=args.org_guid,
                contract_guid=args.contract_guid,
                revoked=False).all():
            g.revoked = True
            revoked += 1
        db.session.commit()

        grant, gst = grant_service.issue_grant(
            args.sr_guid, args.patient_guid, args.org_guid, args.contract_guid,
            grant_type="bidirectional", expires_hours=args.expires_days * 24,
        )
        if gst not in (200, 201):
            print(f"ERROR issuing grant ({gst}): {grant}", file=sys.stderr)
            return 1

    # 3. Print for handover -------------------------------------------------
    line = "=" * 68
    print(f"\n{line}")
    print("PROVIDER CREDENTIALS — hand over on TWO SEPARATE channels")
    print(f"  org      {args.org_guid}")
    print(f"  contract {args.contract_guid}")
    print(f"  SR       {args.sr_guid}")
    print(f"  valid    {args.expires_days} days")
    print(line)
    print("\n[channel 1]  PAT  ->  X-Provider-Token header")
    print(f"  pat_guid : {pat_guid}")
    print(f"  TOKEN    : {pat_raw}")
    print("\n[channel 2]  grant_token  ->  JSON body `grant_token`")
    print(f"  grant_guid : {grant['guid']}")
    print(f"  TOKEN      : {grant['grant_token']}")
    if revoked:
        print(f"\n(note: revoked {revoked} prior grant(s) for this SR+org+contract)")
    print(f"{line}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
