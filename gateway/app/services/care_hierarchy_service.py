"""Resolve an organisation GUID into its vårdgivare / vårdenhet pair.

ips tells us which **organisation** a patient is assigned to. It does not know
whether that organisation is a *vårdgivare* (caregiver — the legal entity) or a
*vårdenhet* (care unit — the one beneath it), because ips's `clinics` table has
no parent column. The hierarchy lives in **sso**, whose `organisations` table
carries `care_organisation_guid` on each unit.

That distinction is not cosmetic. **A vårdenhet is the spärrgräns** — the
boundary a patient's block applies across — so saying which level an
organisation sits at is a legal statement under PDL, not a label. A page that
prints one name and calls it "organisation" leaves the reader unable to tell
whether they are looking at the entity that holds the data or the unit a block
would hide it from.

## Authentication: the CALLER's token, not a service key

These reads forward `session['sso_token']`, so sso applies the caller's own
authorisation. request.pdhc deliberately does not hold an sso service
credential for this — the same choice analyse made for its ips reads, and it
means this page can never show a caller more of the organisation tree than
sso would show them directly.

sso's `require_auth` accepts **only** `Authorization: Bearer <token>`; no
`X-API-Key`, no `X-Service-Key`, no cookie. Sending any of those gets a 401
that names a missing header while the request carried a valid credential.
"""
import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers


class HierarchyUnavailable(RuntimeError):
    """sso could not be asked where this organisation sits in the hierarchy.

    Raised, never returned as an empty answer. "This organisation has no
    caregiver" and "we could not find out" are different statements, and only
    one of them means the data is wrong. Displaying the first when the second
    is true is how a reader concludes a legal relationship is absent.
    """


def _sso_get(path, bearer):
    base = (current_app.config.get('SSO_BASE_URL') or '').rstrip('/')
    if not base:
        raise HierarchyUnavailable('SSO_BASE_URL is not configured')
    if not bearer:
        raise HierarchyUnavailable(
            'no SSO token on this session, so sso cannot be asked — this is a '
            'MISSING CREDENTIAL here, not an sso outage')
    headers = {'Accept': 'application/json',
               'Authorization': f'Bearer {bearer}'}
    headers.update(outbound_session_headers())
    try:
        resp = requests.get(base + path, headers=headers, timeout=10)
    except requests.RequestException as e:
        raise HierarchyUnavailable(f'sso unreachable: {e}') from e
    if resp.status_code != 200:
        raise HierarchyUnavailable(
            f'sso returned {resp.status_code} for {path}')
    data = resp.json()
    return data if isinstance(data, list) else []


def resolve(org_guid, bearer):
    """Where does `org_guid` sit? Returns both levels, with names and guids.

    ::

        {'care_unit':      {'guid': ..., 'name': ...} | None,
         'care_organisation': {'guid': ..., 'name': ...} | None,
         'level': 'care_unit' | 'care_organisation' | 'unknown'}

    `level` says which of the two the given guid actually IS, so a caller can
    render "this is a vårdenhet under that vårdgivare" rather than guessing
    from which field happens to be populated.

    A guid sso does not know returns level `unknown` with both levels None —
    a real answer, distinct from the exception above. ips holding an
    organisation sso never issued is a live condition, not a hypothetical: it
    was #767 and #780.
    """
    want = str(org_guid or '')
    if not want:
        return {'care_unit': None, 'care_organisation': None,
                'level': 'unknown'}

    units = _sso_get('/api/registry/care-units', bearer)
    orgs = _sso_get('/api/registry/care-organisations', bearer)
    org_name = {str(o.get('care_organisation_guid')): o.get('care_organisation_name')
                for o in orgs}

    for u in units:
        if str(u.get('care_unit_guid')) == want:
            parent = str(u.get('care_organisation_guid') or '')
            return {
                'care_unit': {'guid': want, 'name': u.get('care_unit_name')},
                'care_organisation': ({'guid': parent,
                                       'name': org_name.get(parent)}
                                      if parent else None),
                'level': 'care_unit',
            }

    if want in org_name:
        # The guid IS a vårdgivare. There is no unit to show, and inventing
        # one would assert a care unit that does not exist.
        return {'care_unit': None,
                'care_organisation': {'guid': want, 'name': org_name[want]},
                'level': 'care_organisation'}

    return {'care_unit': None, 'care_organisation': None, 'level': 'unknown'}
