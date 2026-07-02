"""Ticket #377 (rollup #348) — emit FHIR R5 corpus for validator gating.

Scope — what this emitter covers (per ADR-001 + the #373 rewrite):

  1. `/api/v1/metadata` — the CapabilityStatement itself.

Scope — what it INTENTIONALLY defers (mirrors termbank's Rule 15 A
narrowing):

  - FHIR R5 ServiceRequest + contained CarePlan/Goal/Questionnaire.
    First conformance run flagged real R4→R5 shape drift in
    `app.services.fhir_builder_service` (CarePlan.activity.detail no
    longer exists in R5; ServiceRequest.code + supportingInfo are
    CodeableReference in R5; Questionnaire.item.type='choice' was
    renamed to 'coding'; `_pdhc_*` markers on the contained CarePlan
    aren't spec-legal; authoredOn missing timezone). Tracked as
    ticket #378 (rollup #348), with the concrete validator findings
    logged there. Once #378 lands the shape fixes, extend this file
    to seed and emit the ServiceRequest envelope too.

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

HERE = os.path.dirname(os.path.abspath(__file__))
GATEWAY = os.path.dirname(HERE)
if GATEWAY not in sys.path:
    sys.path.insert(0, GATEWAY)


def _bootstrap_env(tmp_db_path: str) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db_path}"
    # AUTH_DISABLED=true requires FLASK_ENV=development per config.py
    # guard #91. Corpus emit is offline and doesn't touch auth anyway.
    os.environ["FLASK_ENV"] = "development"
    os.environ["AUTH_DISABLED"] = "true"
    os.environ.setdefault("FLASK_SECRET_KEY", "corpus-emit-not-secret")
    os.environ.setdefault("JWT_SECRET_KEY", "corpus-emit-jwt")
    os.environ.setdefault(
        "HMAC_SECRET", "corpus-emit-hmac-minimum-32-chars-placeholder"
    )
    os.environ.setdefault("INTERNAL_SERVICE_KEY", "corpus-emit-internal")


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

        client = app.test_client()

        print(f"Emitting FHIR R5 corpus → {out_dir}")

        # 1. CapabilityStatement — /api/v1/metadata. This is the only
        # FHIR resource this emitter currently ships; ServiceRequest +
        # contained CarePlan/Goal/Questionnaire are deferred to #378
        # (see module docstring).
        cs = client.get("/api/v1/metadata").get_json()
        _write(out_dir, "capability_statement", cs)

        n = len([f for f in os.listdir(out_dir) if f.endswith(".json")])
        print(f"Done — {n} JSON files.")
    finally:
        os.close(db_fd)
        if os.path.exists(db_path):
            os.remove(db_path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fhir_corpus")
    emit_corpus(out)
