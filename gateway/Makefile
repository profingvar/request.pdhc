# request.pdhc/gateway Makefile — local dev + rollup #348 FHIR
# conformance.
#
# Day-to-day:
#   make test            # run pytest (whole suite)
#
# Rollup #348 conformance surface (per ADR-001 + #373 CapabilityStatement
# rewrite): ServiceRequest with contained CarePlan/Goals/Questionnaires
# is what request.pdhc actually emits; the CapabilityStatement itself
# is a FHIR R5 resource too. The validator gates all three.
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

# Terminology: `n/a` disables the terminology server. request.pdhc's
# concept coding uses PDHC-scoped URNs (`urn:pdhc:concept`,
# `urn:pdhc:unit`, `urn:pdhc:valueset:<guid>`) that no public tx
# server knows about; enabling tx makes validation hang for 60s per
# unknown code (tx5 timeout) and then fail. With tx off, the
# validator emits "Coding is unknown; no verification" as a Note or
# Warning (informational), which is the honest state — plan.pdhc
# owns those code systems and only plan.pdhc can validate them. Well-
# known HL7 codings in the CapabilityStatement are checked from the
# bundled package cache and don't need tx either.
TX_SERVER ?= n/a


.PHONY: help test corpus conformance check-jar

help:
	@echo "Targets: test, corpus, conformance, check-jar"

test:
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
