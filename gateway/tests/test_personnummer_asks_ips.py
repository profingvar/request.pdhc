"""#812 — request.pdhc asks ips whether a personnummer is valid.

The history matters, because it is why this is an HTTP call and not a function.

request.pdhc had its OWN Luhn check. It was deleted earlier because it flagged
`19610115-9638`, which I believed ips's generator had produced and considered
valid. Both halves were false: that value is a hand-written fixture in ips's
`test_euips_header.py`, and ips's validator rejects it. **The local check had
been right**, and removing it left this page silent about broken identifiers —
and silence on an identifier reads as "this one is fine".

Restoring the local check would have reinstated a second implementation of a
rule ips owns, which is the shape that cost #784 and #786 a day each. So ips
grew an endpoint and request asks it.

Three states, and the third is what these tests are mostly about: valid,
invalid-with-a-reason, and **unverified** — we could not ask.
"""
from unittest.mock import patch

import pytest

from app.routes import patients as mod
from app.services import patient_service
from app.services.patient_service import IdentifierCheckUnavailable

PNR_SYSTEM = "urn:oid:1.2.752.129.2.1.3.1"
RID = "612a2995-f95a-4efb-8f6e-e203d339ac5a"


def _patient(value="19610115-1873", birth="1961-01-15"):
    return {
        "resourceType": "Patient", "id": RID,
        "birthDate": birth,
        "name": [{"family": "Testsson", "given": ["Test"]}],
        "identifier": [{"system": PNR_SYSTEM, "value": value}],
    }


RESOLVED = {"care_unit": {"guid": "u-1", "name": "UAS"},
            "care_organisation": {"guid": "o-1", "name": "Region Uppsala"},
            "level": "care_unit"}


def _patches(patient, *, validate=None, validate_exc=None):
    """The real patch set for the patient view, copied from
    TestThePageRenders — `care_hierarchy_service.resolve` is the actual API
    (I first guessed `care_units`/`care_organisations`, which do not exist)."""
    vp = (patch.object(mod.patient_service, "validate_identifiers",
                       side_effect=validate_exc) if validate_exc else
          patch.object(mod.patient_service, "validate_identifiers",
                       return_value=validate if validate is not None else []))
    return [
        patch.object(mod.patient_service, "get_patient",
                     return_value=(patient, 200)),
        patch.object(mod.patient_service, "get_patient_clinics",
                     return_value=[]),
        patch.object(mod, "get_upstream_token", return_value="tok"),
        patch.object(mod.care_hierarchy_service, "resolve",
                     return_value=RESOLVED),
        vp,
    ]


def _render(client, patient, *, validate=None, validate_exc=None):
    import contextlib
    with contextlib.ExitStack() as st:
        for p_ in _patches(patient, validate=validate,
                           validate_exc=validate_exc):
            st.enter_context(p_)
        r = client.get(f"/patients/{RID}")
    return r.get_data(as_text=True)


def test_a_valid_identifier_shows_no_warning(app, client):
    body = _render(client, _patient(), validate=[
        {"value": "19610115-1873", "valid": True, "problem": None,
         "normalised": "19610115-1873"}])
    assert "19610115-1873" in body
    assert "is not valid" not in body
    assert "Not checked" not in body


def test_an_INVALID_identifier_shows_ips_OWN_reason(app, client):
    """The reason comes from ips, verbatim. "invalid personnummer" alone sends
    an operator looking at the wrong thing."""
    reason = ("19610115-9638 has check digit 8; the Luhn digit for "
              "610115963 is 7")
    body = _render(client, _patient(value="19610115-9638"), validate=[
        {"value": "19610115-9638", "valid": False, "problem": reason,
         "normalised": "19610115-9638"}])
    assert "is not valid" in body
    assert "check digit 8" in body
    assert "Luhn digit" in body


def test_UNVERIFIED_is_shown_and_is_NOT_silence(app, client):
    """THE test. When ips cannot be asked, the page must say so.

    The regression this guards against is the one that actually happened:
    the check was removed, nothing replaced it, and a broken identifier
    rendered with no remark at all.
    """
    body = _render(client, _patient(),
                   validate_exc=IdentifierCheckUnavailable("ips unreachable"))
    assert "Not checked" in body, (
        "ips was unreachable and the page said nothing — silence reads as valid")
    assert "not a statement that it is correct" in body
    assert "is not valid" not in body, (
        "unreachable was reported as INVALID; those are different claims")


def test_unverified_is_distinct_from_invalid_in_the_markup(app, client):
    """A reader must be able to tell the two apart at a glance, not only by
    reading the sentence."""
    invalid = _render(client, _patient(value="19610115-9638"), validate=[
        {"value": "19610115-9638", "valid": False, "problem": "bad digit",
         "normalised": "19610115-9638"}])
    unver = _render(client, _patient(),
                    validate_exc=IdentifierCheckUnavailable("boom"))
    assert "is not valid" in invalid and "Not checked" not in invalid
    assert "Not checked" in unver and "is not valid" not in unver


def test_the_page_still_RENDERS_when_ips_is_down(app, client):
    """Degrade, do not 500. The identifier is one field on the page."""
    import contextlib
    with contextlib.ExitStack() as st:
        for p_ in _patches(_patient(),
                           validate_exc=IdentifierCheckUnavailable("down")):
            st.enter_context(p_)
        r = client.get(f"/patients/{RID}")
    assert r.status_code == 200


def test_the_BIRTH_DATE_is_sent_so_ips_can_check_agreement(app, client):
    """The check that matters most here: #789 produced identifiers encoding a
    different birth date from the patient's own record, which neither a length
    check nor a checksum alone catches. ips can only make that call if request
    sends the birth date."""
    seen = {}

    def _capture(items):
        seen["items"] = items
        return [{"value": i["value"], "valid": True, "problem": None,
                 "normalised": i["value"]} for i in items]

    import contextlib
    with contextlib.ExitStack() as st:
        for p_ in _patches(_patient(birth="1961-01-15"),
                           validate_exc=_capture):
            st.enter_context(p_)
        client.get(f"/patients/{RID}")

    assert seen["items"] == [{"value": "19610115-1873",
                              "birth_date": "1961-01-15"}]


def test_a_SHAPE_failure_is_not_sent_to_ips(app, client):
    """A doubled-century value needs no checksum, and asking about it would
    only restate what we already know — so it is named locally and ips is not
    called at all."""
    called = []
    import contextlib
    with contextlib.ExitStack() as st:
        for p_ in _patches(_patient(value="1919580314-8691"),
                           validate_exc=lambda items: called.append(items) or []):
            st.enter_context(p_)
        body = client.get(f"/patients/{RID}").get_data(as_text=True)
    assert called == [], "ips was asked about a value of the wrong shape"
    assert "15 characters" in body


# ---------------------------------------------------------------------------
# The service call itself
# ---------------------------------------------------------------------------

class TestValidateIdentifiersClient:
    """Every failure mode must raise, never return a verdict."""

    def _post(self, app, **kw):
        with app.app_context():
            with patch("app.services.patient_service.requests.post", **kw):
                return patient_service.validate_identifiers(
                    [{"value": "19610115-1873", "birth_date": None}])

    def test_a_transport_error_raises(self, app):
        import requests as rq
        with pytest.raises(IdentifierCheckUnavailable):
            self._post(app, side_effect=rq.RequestException("no route"))

    @pytest.mark.parametrize("code", [401, 403, 404, 500, 502])
    def test_a_non_200_raises(self, app, code):
        """404 included: that is what a request.pdhc deployed against an ips
        predating this endpoint receives, and it must read as "cannot verify",
        never as "valid"."""
        resp = type("R", (), {"status_code": code,
                              "json": lambda self: {}})()
        with pytest.raises(IdentifierCheckUnavailable):
            self._post(app, return_value=resp)

    def test_a_WRONG_LENGTH_response_raises(self, app):
        """The caller zips the results against its own list. A short list
        would silently shift every verdict onto the wrong identifier."""
        resp = type("R", (), {"status_code": 200,
                              "json": lambda self: {"results": []}})()
        with pytest.raises(IdentifierCheckUnavailable):
            self._post(app, return_value=resp)

    def test_non_json_raises(self, app):
        def _boom(self):
            raise ValueError("not json")
        resp = type("R", (), {"status_code": 200, "json": _boom})()
        with pytest.raises(IdentifierCheckUnavailable):
            self._post(app, return_value=resp)

    def test_an_empty_input_short_circuits_without_calling_ips(self, app):
        with app.app_context():
            with patch("app.services.patient_service.requests.post",
                       side_effect=AssertionError("must not be called")):
                assert patient_service.validate_identifiers([]) == []
