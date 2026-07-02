"""Ticket #377 (rollup #348) — emit FHIR R5 corpus for validator gating.

Scope — what this emitter covers (per ADR-001 + the #373 rewrite +
#381 fhir_builder_service R5 fix landing):

  1. `/api/v1/metadata` — the CapabilityStatement itself.
  2. FHIR R5 ServiceRequest — the envelope, with contained CarePlan,
     Goals, Patient excerpt, and Questionnaires. Assembled by
     `app.services.fhir_builder_service.build_service_request_resource`
     — the code path that ships on finalize/push.
  3. FHIR R5 CarePlan standalone — the contained CarePlan extracted
     from the envelope. Emitted separately so a validator failure
     points cleanly at CarePlan-shape drift rather than requiring a
     dig through the envelope.

Boots a self-contained Flask test app on a SQLite tmp DB. No external
HTTP calls (AUTH_DISABLED=true takes care of SSO; nothing in the
CapabilityStatement rendering path talks to plan.pdhc / IPS).

Run:  python gateway/tests/conformance_corpus_emit.py [out_dir]
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = os.path.dirname(HERE)
if GATEWAY not in sys.path:
    sys.path.insert(0, GATEWAY)


# Stable GUIDs so the corpus is deterministic (matches on identical
# runs). validator_cli.jar diff-hashes are cache-friendlier this way.
PATIENT_GUID = "00000000-0000-4000-8000-000000000001"
PLAN_DEFINITION_GUID = "00000000-0000-4000-8000-000000000002"
REQUESTER_USER_GUID = "00000000-0000-4000-8000-000000000003"
REQUESTER_ORG_GUID = "00000000-0000-4000-8000-000000000004"
CONTRACT_GUID = "00000000-0000-4000-8000-000000000005"
FORM_GUID = "00000000-0000-4000-8000-000000000006"
SR_GUID = "00000000-0000-4000-8000-000000000007"
CONCEPT_GUID_1 = "00000000-0000-4000-8000-000000000101"  # HbA1c
CONCEPT_GUID_2 = "00000000-0000-4000-8000-000000000102"  # visit


PLAN_SNAPSHOT = {
    "title": "Diabetes type 2 follow-up",
    "description": (
        "Quarterly HbA1c monitoring with a physical follow-up visit."
    ),
    "goals": [
        {
            "concept_guid": CONCEPT_GUID_1,
            "concept_name": "HbA1c",
            "priority": "high-priority",
            "target_type": "range",
            "target_range_low": 42.0,
            "target_range_high": 52.0,
            "target_unit_name": "mmol/mol",
        },
    ],
    "activities": [
        {
            "guid": "00000000-0000-4000-8000-000000000201",
            "title": "HbA1c measurement",
            "description": "Draw venous blood and measure HbA1c.",
            "performer_type": "nurse",
            "timing_type": "repeat",
            "timing_frequency": 1,
            "timing_period": 3,
            "timing_period_unit": "mo",
            "transactions": [
                {
                    "guid": "00000000-0000-4000-8000-000000000301",
                    "concept_guid": CONCEPT_GUID_1,
                    "concept_name": "HbA1c",
                    "concept_unit_name": "mmol/mol",
                    "expected_value": "45",
                    "range_min": 42.0,
                    "range_max": 52.0,
                    "requirement_type": "required",
                },
            ],
        },
        {
            "guid": "00000000-0000-4000-8000-000000000202",
            "title": "Physical follow-up visit",
            "description": "Annual review of diabetes management.",
            "performer_type": "physician",
            "timing_type": "repeat",
            "timing_frequency": 1,
            "timing_period": 12,
            "timing_period_unit": "mo",
            "transactions": [
                {
                    "guid": "00000000-0000-4000-8000-000000000302",
                    "concept_guid": CONCEPT_GUID_2,
                    "concept_name": "Diabetes follow-up visit",
                    "requirement_type": "required",
                },
            ],
        },
    ],
}


PATIENT_EXCERPT = {
    "resourceType": "Patient",
    "id": PATIENT_GUID,
    "name": [{"family": "Testson", "given": ["Test"]}],
    "gender": "female",
    "birthDate": "1970-01-01",
    # No `identifier` key — the R5 validator flags empty arrays as
    # "Array cannot be empty - the property should not be present if
    # it has no values". Real deployments should add a Swedish
    # personnummer identifier via the swedish IG when adopted.
}


QUESTIONNAIRE_SNAPSHOT = {
    "resourceType": "Questionnaire",
    "status": "active",
    "title": "Diabetes symptom check",
    "item": [
        {
            "linkId": "q1",
            "text": "How would you rate your diabetes symptoms today?",
            # Deliberately kept as 'choice' — the fhir_builder rewrites
            # it to 'coding' on emit. This exercises the R4→R5 rename
            # shim end-to-end.
            "type": "choice",
            "answerOption": [
                {"valueCoding": {
                    "system": "https://plan.pdhc.se/api/v1/lookup/valuesets/symptom-rating",
                    "code": "0", "display": "None"}},
                {"valueCoding": {
                    "system": "https://plan.pdhc.se/api/v1/lookup/valuesets/symptom-rating",
                    "code": "1", "display": "Mild"}},
                {"valueCoding": {
                    "system": "https://plan.pdhc.se/api/v1/lookup/valuesets/symptom-rating",
                    "code": "2", "display": "Moderate"}},
                {"valueCoding": {
                    "system": "https://plan.pdhc.se/api/v1/lookup/valuesets/symptom-rating",
                    "code": "3", "display": "Severe"}},
            ],
        },
    ],
}


def _bootstrap_env(tmp_db_path: str) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db_path}"
    os.environ["FLASK_ENV"] = "development"
    os.environ["AUTH_DISABLED"] = "true"
    os.environ.setdefault("FLASK_SECRET_KEY", "corpus-emit-not-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "corpus-emit-jwt")
    os.environ.setdefault(
        "HMAC_SECRET", "corpus-emit-hmac-minimum-32-chars-placeholder"
    )
    os.environ.setdefault("INTERNAL_SERVICE_KEY", "corpus-emit-internal")


def _seed(app, db) -> str:
    """Insert a fully-formed ServiceRequest + one attached form."""
    from app.models.service_request_models import (
        ServiceRequest, ServiceRequestForm,
    )
    with app.app_context():
        sr = ServiceRequest(
            guid=SR_GUID,
            status="active",
            intent="order",
            priority="routine",
            patient_guid=PATIENT_GUID,
            patient_excerpt=PATIENT_EXCERPT,
            plan_definition_guid=PLAN_DEFINITION_GUID,
            plan_definition_snapshot=PLAN_SNAPSHOT,
            contract_guid=CONTRACT_GUID,
            requester_user_guid=REQUESTER_USER_GUID,
            requester_user_name="Dr Test Requester",
            requester_org_guid=REQUESTER_ORG_GUID,
            requester_org_name="Test Clinic",
            notes="Corpus fixture ServiceRequest.",
            created_at=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        db.session.add(sr)
        db.session.flush()

        srf = ServiceRequestForm(
            guid=str(uuid.UUID(int=8)),
            service_request_guid=SR_GUID,
            form_guid=FORM_GUID,
            form_version="1.0",
            form_snapshot=QUESTIONNAIRE_SNAPSHOT,
            display_title="Diabetes symptom check",
            sort_order=0,
        )
        db.session.add(srf)
        db.session.commit()
        return sr.guid


def _load_seeded_sr(guid):
    """Query the seeded ServiceRequest. Must run inside app_context."""
    from app.models.service_request_models import ServiceRequest
    return ServiceRequest.query.filter_by(guid=guid).first()


def _extract_contained_careplan(sr_resource: dict) -> dict | None:
    """Pull the contained CarePlan out as a standalone resource.

    The extracted CarePlan preserves its `#patient-<x>` and `#goal-N`
    hash references to the peer Patient + Goal resources it was
    contained alongside. To validate cleanly in isolation, we lift
    those peers into the CarePlan's own `contained[]` so the
    validator can resolve every hash reference the CarePlan makes.
    """
    peer_contained = sr_resource.get("contained", []) or []
    careplan = None
    for entry in peer_contained:
        if entry.get("resourceType") == "CarePlan":
            careplan = dict(entry)
            break
    if careplan is None:
        return None

    # Which peer resources does this CarePlan reference?
    subject_ref = (careplan.get("subject") or {}).get("reference", "")
    goal_refs = [
        g.get("reference", "") for g in (careplan.get("goal") or [])
    ]
    needed_ids = set()
    for ref in [subject_ref] + goal_refs:
        if ref.startswith("#"):
            needed_ids.add(ref[1:])

    carried = []
    for entry in peer_contained:
        entry_id = entry.get("id")
        if entry_id in needed_ids and entry.get("resourceType") != "CarePlan":
            carried.append(entry)

    if carried:
        careplan["contained"] = carried
    return careplan


def _write(out_dir: str, name: str, body: dict) -> None:
    path = os.path.join(out_dir, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"  wrote {path}")


def emit_corpus(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    try:
        _bootstrap_env(db_path)
        from app import create_app, db as _db

        app = create_app(testing=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
        with app.app_context():
            _db.create_all()

        sr_guid = _seed(app, _db)
        client = app.test_client()

        print(f"Emitting FHIR R5 corpus → {out_dir}")

        # 1. CapabilityStatement.
        cs = client.get("/api/v1/metadata").get_json()
        _write(out_dir, "capability_statement", cs)

        # 2. ServiceRequest envelope with contained resources.
        from app.services.fhir_builder_service import (
            build_service_request_resource,
        )
        with app.app_context():
            sr_model = _load_seeded_sr(sr_guid)
            sr_resource = build_service_request_resource(sr_model)
        _write(out_dir, "service_request", sr_resource)

        # 3. Standalone CarePlan (extracted from the envelope).
        cp = _extract_contained_careplan(sr_resource)
        if cp is not None:
            _write(out_dir, "care_plan", cp)
        else:
            print("  WARN: no contained CarePlan in ServiceRequest — "
                  "skipping care_plan.json")

        n = len([f for f in os.listdir(out_dir) if f.endswith(".json")])
        print(f"Done — {n} JSON files.")
    finally:
        os.close(db_fd)
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fhir_corpus")
    emit_corpus(out)
