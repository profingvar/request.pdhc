"""The create page's patient selector: scoped by organisation, sourced from ips.

Two things changed and these tests pin both.

**The organisation comes first and decides the patient list.** It used to be
the other way round: the page fetched every patient in ips and filtered them in
Python on `Patient.managingOrganization`, while a separate "Requesting
organisation" control sat further down for chain-of-custody. Nothing stopped
the two disagreeing.

**The list is assignment-based.** `PatientClinicAssignment` is the record;
`managingOrganization` is a projection of it that can drift — ips reports the
disagreement as `custodian_mismatch` (#792) rather than resolving it quietly,
and the projection is single-valued where the assignment is many-to-many.

Measured on production 2026-10-08 before the change: 122 of 122 assigned
patients agreed and none was multi-org, so the old filter hid **nobody**. It
was wrong in the way that waits — the first patient moved between clinics, or
assigned to two, is the one it gets wrong, and the symptom is a clinician
unable to find their own patient.
"""
from unittest.mock import patch

import pytest

from app.routes.service_requests import _clinics_for_orgs
from app.services import patient_service
from app.services.patient_service import PatientListUnavailable


# Two DIFFERENT guid spaces. The whole point of _clinics_for_orgs is that an
# SSO blob names ORGANISATIONS while ips's endpoint is keyed by CLINIC, and
# `clinics.guid` != `clinics.organisation_guid`.
ORG_A = "org-aaaa-0000-0000-0000-000000000001"
CLINIC_A = "clinic-aaaa-0000-0000-0000-00000000000a"
ORG_B = "org-bbbb-0000-0000-0000-000000000002"
CLINIC_B = "clinic-bbbb-0000-0000-0000-00000000000b"

IPS_CLINICS = [
    {"guid": CLINIC_A, "organisation_guid": ORG_A, "name": "Alfa Vårdcentral"},
    {"guid": CLINIC_B, "organisation_guid": ORG_B, "name": "Beta Vårdcentral"},
    # A clinic with no organisation cannot be matched to an affiliation.
    {"guid": "clinic-orphan", "organisation_guid": None, "name": "Orphan"},
]


class TestOrgToClinicResolution:
    """#779 in miniature: these are two identifier spaces, not one."""

    def test_an_org_guid_resolves_to_a_DIFFERENT_clinic_guid(self, app):
        with app.app_context(), \
                patch.object(patient_service, "list_clinics",
                             return_value=IPS_CLINICS):
            out = _clinics_for_orgs([ORG_A])
        assert len(out) == 1
        assert out[0]["org_guid"] == ORG_A
        assert out[0]["clinic_guid"] == CLINIC_A
        # The assertion that matters: they are not the same value, so a
        # version of this code that passed the org guid straight to
        # /clinics/<guid>/patients would 404 for every caller.
        assert out[0]["clinic_guid"] != out[0]["org_guid"]

    def test_only_the_callers_orgs_come_back(self, app):
        with app.app_context(), \
                patch.object(patient_service, "list_clinics",
                             return_value=IPS_CLINICS):
            out = _clinics_for_orgs([ORG_B])
        assert [c["clinic_guid"] for c in out] == [CLINIC_B]

    def test_su_admin_gets_every_org_backed_clinic(self, app):
        with app.app_context(), \
                patch.object(patient_service, "list_clinics",
                             return_value=IPS_CLINICS):
            out = _clinics_for_orgs([], all_orgs=True)
        assert {c["clinic_guid"] for c in out} == {CLINIC_A, CLINIC_B}

    def test_a_clinic_with_no_organisation_is_skipped(self, app):
        """Selecting it would scope a request to an organisation that does not
        exist, which is worse than not offering it."""
        with app.app_context(), \
                patch.object(patient_service, "list_clinics",
                             return_value=IPS_CLINICS):
            out = _clinics_for_orgs([], all_orgs=True)
        assert all(c["clinic_guid"] != "clinic-orphan" for c in out)

    def test_an_ips_failure_propagates_rather_than_returning_empty(self, app):
        """An empty list would read as "you belong to no organisation"."""
        with app.app_context(), \
                patch.object(patient_service, "list_clinics",
                             side_effect=PatientListUnavailable("ips down")):
            with pytest.raises(PatientListUnavailable):
                _clinics_for_orgs([ORG_A])


class TestPatientListSource:
    """The list must come from the ASSIGNMENT endpoint, not /fhir/Patient."""

    def test_it_calls_the_clinic_patients_endpoint(self, app):
        seen = {}

        class R:
            status_code = 200

            @staticmethod
            def json():
                return [{"guid": "p1", "family_name": "Lind",
                         "given_name": "Eva", "birth_date": "1980-01-01"}]

        def fake_get(url, **kw):
            seen["url"] = url
            return R()

        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = "k" * 10
            with patch.object(patient_service.requests, "get", fake_get):
                out = patient_service.list_clinic_patients(CLINIC_A)

        assert out[0]["family_name"] == "Lind"
        assert seen["url"] == (
            "http://ips.test/api/v1/clinics/%s/patients" % CLINIC_A)
        # The old path asked for every patient and filtered locally.
        assert "/fhir/Patient" not in seen["url"]

    def test_the_key_goes_out_as_authorization_apikey(self, app):
        """ips reads ONLY `Authorization`; `X-API-Key` is ignored silently."""
        seen = {}

        class R:
            status_code = 200

            @staticmethod
            def json():
                return []

        def fake_get(url, **kw):
            seen["headers"] = kw.get("headers") or {}
            return R()

        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = "secret-key"
            with patch.object(patient_service.requests, "get", fake_get):
                patient_service.list_clinic_patients(CLINIC_A)

        assert seen["headers"].get("Authorization") == "ApiKey secret-key"

    def test_404_is_a_genuine_empty_not_a_failure(self, app):
        """ips knowing of no such clinic is an ANSWER."""
        class R:
            status_code = 404
            text = ""

        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = "k"
            with patch.object(patient_service.requests, "get",
                              lambda *a, **k: R()):
                assert patient_service.list_clinic_patients(CLINIC_A) == []

    @pytest.mark.parametrize("code", [401, 403, 500, 502])
    def test_a_4xx_or_5xx_RAISES_rather_than_returning_empty(self, app, code):
        """THE central property.

        A clinician shown an empty patient selector concludes there is nobody
        to request for. If the truth is "ips could not be asked", that is a
        different problem with a different fix, and returning `[]` makes the
        two indistinguishable — the mistake that let this service's spärr
        filter hide nothing for months while looking healthy (#783).
        """
        class R:
            status_code = code
            text = "nope"

        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = "k"
            with patch.object(patient_service.requests, "get",
                              lambda *a, **k: R()):
                with pytest.raises(PatientListUnavailable):
                    patient_service.list_clinic_patients(CLINIC_A)

    def test_a_missing_credential_is_named_as_such(self, app):
        """A 401 with no key configured is OUR bug, not an ips outage."""
        class R:
            status_code = 401
            text = ""

        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = ""
            with patch.object(patient_service.requests, "get",
                              lambda *a, **k: R()):
                with pytest.raises(PatientListUnavailable) as e:
                    patient_service.list_clinics()
        assert "MISSING CREDENTIAL" in str(e.value)

    def test_a_transport_error_is_also_unavailable(self, app):
        import requests as http
        with app.app_context():
            app.config["IPS_BASE_URL"] = "http://ips.test"
            app.config["IPS_API_KEY"] = "k"
            with patch.object(patient_service.requests, "get",
                              side_effect=http.ConnectionError("down")):
                with pytest.raises(PatientListUnavailable):
                    patient_service.list_clinic_patients(CLINIC_A)


class TestThePageItself:
    """Through the real route, not the helpers.

    The helpers above are proven; a guard is only worth something if the page
    actually applies it. Asserting a predicate is not asserting the gate runs
    — the lesson #729 cost five months.
    """

    def _get(self, app, client, *, orgs, is_su=False, query="",
             clinics=IPS_CLINICS, patients=None):
        import app.routes.service_requests as mod
        # The reform blob keys an affiliation by `care_unit_guid` — a
        # vårdenhet IS an organisation, and that guid is the same value ips
        # stores as `clinics.organisation_guid`. Getting this wrong is how the
        # first version of these tests "failed": `caller_org_ids` returned []
        # for an affiliations[] whose entries lacked the key, and because the
        # list was non-empty it never fell back to `organization_ids` either.
        blob = {"is_su_admin": is_su,
                "affiliations": [{"care_unit_guid": o,
                                  "care_unit_name": "Affil " + o[:8]}
                                 for o in orgs],
                "organization_ids": list(orgs),
                "email": "t@example.test"}
        pts = patients if patients is not None else [
            {"guid": "p-alfa", "family_name": "Alfason", "given_name": "Ann",
             "birth_date": "1970-01-01"}]
        with patch.object(mod, "get_current_access_blob", return_value=blob), \
             patch.object(mod, "get_current_user_guid", return_value="u1"), \
             patch.object(patient_service, "list_clinics",
                          return_value=clinics), \
             patch.object(patient_service, "list_clinic_patients",
                          return_value=pts), \
             patch.object(mod.plan_definition_service, "list_plan_definitions",
                          return_value=([], 200)), \
             patch.object(mod.form_service, "list_forms",
                          return_value=([], 200)):
            return client.get("/service-requests/create" + query)

    def test_one_affiliation_is_chosen_for_the_user(self, app, client):
        r = self._get(app, client, orgs=[ORG_A])
        body = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "Alfason" in body, "the single org's patients should be listed"
        # The scoping choice is the chain-of-custody value.
        assert 'name="requesting_org_guid" value="%s"' % ORG_A in body

    def test_the_access_blob_name_is_preferred_over_the_ips_name(
            self, app, client):
        """Deliberate, and the reason is worth keeping.

        The blob name is what the caller has been TOLD they belong to. ips's
        clinic name is a second copy. Showing the blob's means that when the
        two disagree the caller sees a label they may not recognise — which is
        a prompt to ask — rather than the page quietly picking one and making
        the disagreement invisible. Same instinct as ips reporting
        `custodian_mismatch` instead of resolving it (#792).
        """
        r = self._get(app, client, orgs=[ORG_A])
        body = r.get_data(as_text=True)
        assert "Affil org-aaaa" in body          # from the blob
        assert "Alfa Vårdcentral" not in body    # ips's copy, not preferred

    def test_the_ips_name_is_the_fallback_when_the_blob_has_none(
            self, app, client):
        """A blob without a name must still produce a readable label, not a
        bare guid."""
        import app.routes.service_requests as mod
        blob = {"is_su_admin": False,
                "affiliations": [{"care_unit_guid": ORG_A}],  # no name
                "organization_ids": [ORG_A], "email": "t@example.test"}
        with patch.object(mod, "get_current_access_blob", return_value=blob), \
             patch.object(mod, "get_current_user_guid", return_value="u1"), \
             patch.object(patient_service, "list_clinics",
                          return_value=IPS_CLINICS), \
             patch.object(patient_service, "list_clinic_patients",
                          return_value=[]), \
             patch.object(mod.plan_definition_service, "list_plan_definitions",
                          return_value=([], 200)), \
             patch.object(mod.form_service, "list_forms",
                          return_value=([], 200)):
            r = client.get("/service-requests/create")
        assert "Alfa Vårdcentral" in r.get_data(as_text=True)

    def test_two_affiliations_require_a_choice_and_list_nobody_yet(
            self, app, client):
        r = self._get(app, client, orgs=[ORG_A, ORG_B])
        body = r.get_data(as_text=True)
        assert "Pick an organisation above to see its patients." in body
        assert "Alfason" not in body

    def test_choosing_an_org_lists_its_patients(self, app, client):
        r = self._get(app, client, orgs=[ORG_A, ORG_B],
                      query="?org=" + ORG_B)
        body = r.get_data(as_text=True)
        assert "Alfason" in body
        assert 'name="requesting_org_guid" value="%s"' % ORG_B in body

    def test_a_non_su_cannot_scope_to_an_org_they_lack(self, app, client):
        """Query-string tampering must not widen the patient list.

        The POST handler already refuses a foreign `requesting_org_guid`; this
        pins that the GET scope refuses it too, so a caller cannot even SEE
        another organisation's patients, which is the disclosure half of the
        same rule.
        """
        r = self._get(app, client, orgs=[ORG_A], query="?org=" + ORG_B)
        body = r.get_data(as_text=True)
        assert "not one of yours" in body
        # Having rejected the foreign org, it must not then fall back to
        # listing anything for it.
        assert 'value="%s"' % ORG_B not in body

    def test_an_ips_failure_says_so_instead_of_showing_an_empty_list(
            self, app, client):
        """The property this whole reform turns on.

        An empty `<select>` reads as "this organisation has no patients". If
        ips could not be asked, the page must say that instead.
        """
        import app.routes.service_requests as mod
        blob = {"is_su_admin": False,
                "affiliations": [{"care_unit_guid": ORG_A,
                                  "care_unit_name": "Alfa"}],
                "organization_ids": [ORG_A], "email": "t@example.test"}
        with patch.object(mod, "get_current_access_blob", return_value=blob), \
             patch.object(mod, "get_current_user_guid", return_value="u1"), \
             patch.object(patient_service, "list_clinics",
                          return_value=IPS_CLINICS), \
             patch.object(patient_service, "list_clinic_patients",
                          side_effect=PatientListUnavailable(
                              "ips returned 503")), \
             patch.object(mod.plan_definition_service, "list_plan_definitions",
                          return_value=([], 200)), \
             patch.object(mod.form_service, "list_forms",
                          return_value=([], 200)):
            r = client.get("/service-requests/create")
        body = r.get_data(as_text=True)
        assert "could not be loaded from ips" in body
        assert "ips returned 503" in body
        assert 'is <em>not</em> "no patients"' in body
        assert '<select name="patient_guid"' not in body, (
            "an empty selector must not be offered when the list is unknown")

    def test_a_genuinely_empty_org_says_ips_answered(self, app, client):
        """Zero patients and an unreachable ips must not look alike."""
        r = self._get(app, client, orgs=[ORG_A], patients=[])
        body = r.get_data(as_text=True)
        assert "0 patients" in body
        assert "ips answered" in body
        assert "could not be loaded from ips" not in body
