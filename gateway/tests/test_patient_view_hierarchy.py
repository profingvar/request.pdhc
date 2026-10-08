"""The patient view: all available info, with BOTH organisation levels.

Three properties, each of which the old view got wrong by omission:

* The **personnummer** was not displayed at all — and some patients carry a
  broken one (#789 produced 15-character values with the century doubled).
  A page that omits an identifier cannot show that it is wrong.
* **Caregiver and care unit** were not distinguished. A vårdenhet is the
  *spärrgräns* — the boundary a patient block applies across — so which level
  an organisation sits at is a legal fact under PDL, not a label.
* The **assignment** was never read. `managingOrganization` is a projection of
  it that can drift; ips reports the disagreement as `custodian_mismatch`
  (#792) rather than resolving it.
"""
from unittest.mock import patch

import pytest

from app.services import care_hierarchy_service, patient_service
from app.services.care_hierarchy_service import HierarchyUnavailable
from app.services.patient_service import PatientListUnavailable
from app.routes.patients import _personnummer_problem

RID = "612a2995-f95a-4efb-8f6e-e203d339ac5a"
UNIT_ORG = "7d55624c-1571-44b8-849d-ea5ff0cc1563"
PARENT_ORG = "parent-0000-0000-0000-000000000001"

UNITS = [{"care_unit_guid": UNIT_ORG, "care_unit_name": "UAS",
          "care_organisation_guid": PARENT_ORG}]
ORGS = [{"care_organisation_guid": PARENT_ORG,
         "care_organisation_name": "Region Uppsala"}]


class TestPersonnummerShapeCheck:
    """Shape only. The checksum is ips's job and mine was WRONG."""

    def test_the_real_broken_value_is_flagged(self):
        """1919580314-8691 is on a live patient: "19" + "19580314"."""
        p = _personnummer_problem("1919580314-8691")
        assert p and "15 characters" in p

    @pytest.mark.parametrize("ok", ["19580314-8691", "19610115-9638",
                                    "580314-8691"])
    def test_well_formed_values_are_not_accused(self, ok):
        """An earlier version computed Luhn here and got it wrong, reporting
        19610115-9638 — which ips's own generator produced — as invalid.
        Telling a clinician a real identifier is broken is worse than saying
        nothing, so there is no checksum here to disagree with ips."""
        assert _personnummer_problem(ok) is None


class TestHierarchyResolution:
    def test_a_care_unit_resolves_to_BOTH_levels_with_names_and_guids(self, app):
        with app.app_context():
            app.config["SSO_BASE_URL"] = "http://sso.test"
            with patch.object(care_hierarchy_service, "_sso_get",
                              side_effect=[UNITS, ORGS]):
                r = care_hierarchy_service.resolve(UNIT_ORG, "tok")
        assert r["level"] == "care_unit"
        assert r["care_unit"] == {"guid": UNIT_ORG, "name": "UAS"}
        assert r["care_organisation"] == {"guid": PARENT_ORG,
                                          "name": "Region Uppsala"}

    def test_a_caregiver_guid_has_no_invented_care_unit(self, app):
        """Naming a unit that does not exist would assert a spärrgräns."""
        with app.app_context():
            app.config["SSO_BASE_URL"] = "http://sso.test"
            with patch.object(care_hierarchy_service, "_sso_get",
                              side_effect=[UNITS, ORGS]):
                r = care_hierarchy_service.resolve(PARENT_ORG, "tok")
        assert r["level"] == "care_organisation"
        assert r["care_unit"] is None
        assert r["care_organisation"]["name"] == "Region Uppsala"

    def test_an_org_sso_does_not_know_is_unknown_not_empty(self, app):
        """ips holding an org sso never issued is real — #767, #780."""
        with app.app_context():
            app.config["SSO_BASE_URL"] = "http://sso.test"
            with patch.object(care_hierarchy_service, "_sso_get",
                              side_effect=[UNITS, ORGS]):
                r = care_hierarchy_service.resolve("never-issued", "tok")
        assert r["level"] == "unknown"
        assert r["care_unit"] is None and r["care_organisation"] is None

    def test_no_token_is_named_as_a_missing_credential(self, app):
        with app.app_context():
            app.config["SSO_BASE_URL"] = "http://sso.test"
            with pytest.raises(HierarchyUnavailable) as e:
                care_hierarchy_service._sso_get("/x", None)
        assert "MISSING CREDENTIAL" in str(e.value)

    def test_the_caller_token_goes_out_as_bearer(self, app):
        """sso's require_auth reads ONLY `Authorization: Bearer`."""
        seen = {}

        class R:
            status_code = 200

            @staticmethod
            def json():
                return []

        with app.app_context():
            app.config["SSO_BASE_URL"] = "http://sso.test"
            with patch.object(care_hierarchy_service.requests, "get",
                              lambda url, **kw: (seen.update(
                                  headers=kw.get("headers") or {}), R())[1]):
                care_hierarchy_service._sso_get("/api/registry/care-units", "tok-123")
        assert seen["headers"].get("Authorization") == "Bearer tok-123"


class TestThePageRenders:
    def _get(self, client, *, patient, assignments=None, assign_exc=None,
             resolved=None, resolve_exc=None):
        import app.routes.patients as mod
        a = assignments if assignments is not None else []
        with patch.object(mod.patient_service, "get_patient",
                          return_value=(patient, 200)), \
             patch.object(mod.patient_service, "get_patient_clinics",
                          side_effect=assign_exc) if assign_exc else \
             patch.object(mod.patient_service, "get_patient_clinics",
                          return_value=a), \
             patch.object(mod, "get_upstream_token", return_value="tok"), \
             patch.object(mod.care_hierarchy_service, "resolve",
                          side_effect=resolve_exc) if resolve_exc else \
             patch.object(mod.care_hierarchy_service, "resolve",
                          return_value=resolved or {
                              "care_unit": {"guid": UNIT_ORG, "name": "UAS"},
                              "care_organisation": {"guid": PARENT_ORG,
                                                    "name": "Region Uppsala"},
                              "level": "care_unit"}):
            return client.get("/patients/" + RID)

    def _patient(self, **over):
        p = {"resourceType": "Patient", "id": RID,
             "name": [{"family": "Testsson", "given": ["Eva"]}],
             "gender": "female", "birthDate": "1958-03-14",
             "identifier": [{"system": "urn:oid:1.2.752.129.2.1.3.1",
                             "value": "1919580314-8691"}],
             "managingOrganization": {"display": "UAS",
                                      "reference": "Organization/" + UNIT_ORG}}
        p.update(over)
        return p

    def test_it_shows_both_levels_with_name_AND_guid(self, app, client):
        r = self._get(client, patient=self._patient(),
                      assignments=[{"guid": "clinic-1", "name": "UAS",
                                    "organisation_guid": UNIT_ORG}])
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        for needed in ("Care unit (vårdenhet)", "Caregiver (vårdgivare)",
                       "UAS", UNIT_ORG, "Region Uppsala", PARENT_ORG,
                       "spärrgräns"):
            assert needed in body, needed

    def test_it_shows_the_personnummer_and_flags_it(self, app, client):
        r = self._get(client, patient=self._patient(),
                      assignments=[{"guid": "c", "name": "UAS",
                                    "organisation_guid": UNIT_ORG}])
        body = r.get_data(as_text=True)
        assert "1919580314-8691" in body, "the identifier was not displayed"
        assert "not valid" in body
        assert "doubled-century" in body or "15 characters" in body

    def test_no_assignment_says_ips_answered_none(self, app, client):
        """The live state of the patient in the ticket: 28 of 150 are here."""
        r = self._get(client, patient=self._patient(), assignments=[])
        body = r.get_data(as_text=True)
        assert "records no clinic assignment" in body
        assert "invisible to every organisation-scoped reader" in body
        # And the mismatch is called out, because managingOrganization IS set.
        assert "These two disagree" in body

    def test_an_assignment_read_failure_is_not_shown_as_none(self, app, client):
        r = self._get(client, patient=self._patient(),
                      assign_exc=PatientListUnavailable("ips returned 503"))
        body = r.get_data(as_text=True)
        assert "could not be read from ips" in body
        assert "ips returned 503" in body
        assert 'is <em>not</em> "no assignment"' in body
        assert "records no clinic assignment" not in body

    def test_an_sso_failure_keeps_the_ips_guids_and_says_what_is_unknown(
            self, app, client):
        r = self._get(client, patient=self._patient(),
                      assignments=[{"guid": "c", "name": "UAS",
                                    "organisation_guid": UNIT_ORG}],
                      resolve_exc=HierarchyUnavailable("sso returned 401"))
        body = r.get_data(as_text=True)
        assert "sso could not be asked" in body
        assert UNIT_ORG in body, "the ips org guid is still correct and shown"
        assert "only the caregiver/care-unit" in body

    def test_the_full_resource_is_available_verbatim(self, app, client):
        """A field nobody thought to render is invisible otherwise."""
        r = self._get(client, patient=self._patient(
            communication=[{"language": {"coding": [{"code": "fi-FI"}]},
                            "preferred": True}]),
            assignments=[{"guid": "c", "name": "UAS",
                          "organisation_guid": UNIT_ORG}])
        body = r.get_data(as_text=True)
        assert "Full FHIR Patient resource" in body
        assert "fi-FI" in body


# A catalogue shaped like ips's real response: 17 headings across four
# obligation levels, with all three states represented.
SECTIONS_RESP = {
    "patient_guid": "eaf95fd1-9cc5-4f51-af6f-ae9ec8f6f02b",
    "sections": (
        [{"key": "allergies", "title": "Allergies and intolerances",
          "obligation": "required", "status": "EXPLICITLY_ABSENT",
          "resource_types": ["AllergyIntolerance"]},
         {"key": "problems", "title": "Problem list (active conditions)",
          "obligation": "required", "status": "PRESENT",
          "resource_types": ["Condition"]},
         {"key": "medications", "title": "Medication summary",
          "obligation": "required", "status": "PRESENT",
          "resource_types": ["MedicationStatement"]}]
        + [{"key": "r%d" % i, "title": "Recommended %d" % i,
            "obligation": "recommended", "status": "PRESENT",
            "resource_types": ["Immunization"]} for i in range(4)]
        + [{"key": "o%d" % i, "title": "Optional %d" % i,
            "obligation": "optional", "status": "MISSING",
            "resource_types": ["Observation"]} for i in range(7)]
        + [{"key": "e%d" % i, "title": "EU addition %d" % i,
            "obligation": "eu_addition", "status": "MISSING",
            "resource_types": ["Flag"]} for i in range(3)]),
    "summary": {},
    "required_sections_missing": [],
    "conformant": True,
    "codes_verified": False,
    "disclaimer": "NOT a claim of EU/EHDS conformance",
}

HEADER_RESP = {
    "patient_guid": "eaf95fd1-9cc5-4f51-af6f-ae9ec8f6f02b",
    "elements": {
        "patient_id": {"status": "present", "where": "Patient.identifier"},
        "contact_person": {"status": "present",
                           "where": "RelatedPerson(C) + Patient.contact"},
        "legal_guardian": {"status": "not_applicable",
                           "where": "RelatedPerson(GUARD) — minors only",
                           "why": "patient is an adult, so a guardian would "
                                  "be invented"},
        "health_insurance": {"status": "missing", "where": "Coverage"},
    },
    "missing": ["health_insurance"],
    "complete": False,
    "codes_verified": False,
    "custodian_mismatch": None,
}


class TestEuipsPanels:
    """All 17 euIPS headings, and the document header, on the page."""

    def _get(self, client, *, sections=SECTIONS_RESP, header=HEADER_RESP,
             exc=None):
        import app.routes.patients as mod
        patient = {"resourceType": "Patient", "id": RID,
                   "name": [{"family": "Testsson", "given": ["Eva"]}],
                   "birthDate": "1958-03-14", "identifier": []}
        pm = (patch.object(mod.patient_service, "get_euips_sections",
                           side_effect=exc)
              if exc else
              patch.object(mod.patient_service, "get_euips_sections",
                           return_value=sections))
        with patch.object(mod.patient_service, "get_patient",
                          return_value=(patient, 200)), \
             patch.object(mod.patient_service, "get_patient_clinics",
                          return_value=[]), \
             patch.object(mod, "get_upstream_token", return_value=None), \
             pm, \
             patch.object(mod.patient_service, "get_euips_header",
                          return_value=header):
            return client.get("/patients/" + RID)

    def test_every_one_of_the_17_headings_is_rendered(self, app, client):
        """The ask was whether the page holds ALL the euIPS headings."""
        body = self._get(client).get_data(as_text=True)
        for sec in SECTIONS_RESP["sections"]:
            assert sec["title"] in body, "missing heading: " + sec["title"]
        assert "17" in body, "the catalogue size should be stated"

    def test_all_four_obligation_levels_are_shown(self, app, client):
        body = self._get(client).get_data(as_text=True)
        for lvl in ("required", "recommended", "optional", "eu addition"):
            assert lvl in body, lvl

    def test_explicitly_absent_is_distinguished_from_missing(self, app, client):
        """The distinction the whole three-state design exists for.

        "No allergies recorded" and "a clinician confirmed there are none" are
        different clinical statements, and the guideline REQUIRES the second
        rather than an empty section.
        """
        body = self._get(client).get_data(as_text=True)
        assert "Explicitly absent" in body
        assert "not a gap" in body
        assert "Missing" in body

    def test_conformance_is_not_claimed_as_eu_conformance(self, app, client):
        body = self._get(client).get_data(as_text=True)
        assert "not a claim of EU conformance" in body
        assert "codes_verified" in body

    def test_the_document_header_lists_its_elements(self, app, client):
        body = self._get(client).get_data(as_text=True)
        assert "euIPS document header" in body
        assert "Contact person" in body
        assert "Health insurance" in body
        assert "health_insurance" in body, "the missing element is named"

    def test_an_adult_guardian_reads_not_applicable_not_missing(
            self, app, client):
        """Scoring it as a gap would push a generator toward inventing one."""
        body = self._get(client).get_data(as_text=True)
        assert "Not applicable" in body
        assert "would be invented" in body

    def test_a_failure_says_the_summary_was_not_assessed(self, app, client):
        """"No sections" and "could not ask" are different statements."""
        body = self._get(client, exc=PatientListUnavailable(
            "ips returned 503")).get_data(as_text=True)
        assert "could not be read from ips" in body
        assert 'is <em>not</em> "no sections"' in body
        assert "Allergies and intolerances" not in body
