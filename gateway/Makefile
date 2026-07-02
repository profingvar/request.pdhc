# request.pdhc/gateway Makefile — local dev + rollup #348 FHIR
# conformance.
#
# Day-to-day:
#   make test            # run pytest (mirrors CI ignores in test.yml)
#   make test-all        # run pytest INCLUDING the SSO-fixture files
#
# Rollup #348 conformance surface (per ADR-001 + #373 CapabilityStatement
# rewrite): ServiceRequest with contained CarePlan/Goals/Questionnaires
# is what request.pdhc actually emits; the CapabilityStatement itself
# is a FHIR R5 resource too. The validator gates both.
#
#   make corpus          # emit CapabilityStatement + ServiceRequest +
#                        # CarePlan into gateway/tests/fhir_corpus/*.json
#   make conformance     # validate the corpus against HL7 R5
#                        # validator_cli.jar (requires VALIDATOR_JAR
#                        # to point to a downloaded copy)

VENV ?= venv
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest

VALIDATOR_JAR ?= $(HOME)/.local/share/fhir/validator_cli.jar
CORPUS_DIR := tests/fhir_corpus
FHIR_VERSION := 5.0.0

# Terminology server. Mirrors termbank/plan.pdhc's Makefile so the
# validator can resolve HL7-canonical URLs it needs at runtime.
TX_SERVER ?= https://tx.fhir.org/r5


.PHONY: help test test-all corpus conformance check-jar

help:
	@echo "Targets: test, test-all, corpus, conformance, check-jar"

# Mirror .github/workflows/test.yml — SSO-fixture-affected files are
# ignored until the follow-up (ticket referenced in test.yml header) is
# resolved. Same list, same deselection.
test:
	PYTHONPATH=. $(PYTEST) tests \
		--ignore=tests/test_request_feed.py \
		--ignore=tests/test_care_plans.py \
		--ignore=tests/test_internal_api.py \
		--ignore=tests/test_patients.py \
		--ignore=tests/test_auth.py \
		--ignore=tests/test_providers.py \
		--ignore=tests/test_dispatch.py \
		--deselect tests/test_consent_at_dispatch.py::TestRoutePlumbing::test_bad_payload_concept_guids_shape_is_400 \
		-q

test-all:
	PYTHONPATH=. $(PYTEST) tests -q

corpus:
	@mkdir -p $(CORPUS_DIR)
	$(PY) tests/conformance_corpus_emit.py $(CORPUS_DIR)
	@echo "Corpus refreshed at $(CORPUS_DIR)/"
	@ls -1 $(CORPUS_DIR)/*.json | wc -l | xargs -I{} echo "{} JSON files"

check-jar:
	@if [ ! -f "$(VALIDATOR_JAR)" ]; then \
		echo "MISSING $(VALIDATOR_JAR)"; \
		echo "Download from https://github.com/hapifhir/org.hl7.fhir.core/releases/latest"; \
		echo "and place at $(VALIDATOR_JAR), or pass VALIDATOR_JAR=<path>."; \
		exit 1; \
	fi

conformance: check-jar corpus
	@echo "Validating $(CORPUS_DIR)/*.json against FHIR R5 (tx: $(TX_SERVER))..."
	java -jar "$(VALIDATOR_JAR)" -version $(FHIR_VERSION) -tx=$(TX_SERVER) $(CORPUS_DIR)/*.json
