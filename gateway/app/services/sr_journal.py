"""#1054: the JournalBestallning elements of a ServiceRequest (record.pdhc
stage 2; sketch section 6).

  identifier      system https://request.pdhc.se/fhir/NamingSystem/order-id,
                  value = the order's GUID. Not a human order number: the guid
                  is already unique, stable and platform-wide (Rule 18), it is
                  what every other service already uses to point at an order,
                  and a sequence would need a second allocator and could not be
                  minted for the orders written before #1054. A short display
                  form (first 8 characters) is what the UI shows.
  reason          R5 CodeableReference[]: a code, or a reference to a
                  Condition / Observation / DiagnosticReport /
                  DocumentReference / DetectedIssue / Procedure.
  note            `notes` (written with the order) + `annotations` (appended
                  after it left draft, each with author and time).
  encounter       Encounter/<guid> in the CDR. Optional now (plan D2: required
                  for journal orders once record.pdhc creates encounters).
  replaces        ServiceRequest/<guid>[]; revoked when this one is finalized.
  supportingInfo  extra CodeableReferences, e.g. ClinicalImpression/<guid>.

Pure functions: no database, no Flask. The FHIR builder and the version
renderer both apply `apply_journal_elements`, so a version read back from
history and a freshly built order carry the elements the same way.
"""
from __future__ import annotations

import copy
import re

IDENTIFIER_SYSTEM = 'https://request.pdhc.se/fhir/NamingSystem/order-id'
ENCOUNTER_IDENTIFIER_SYSTEM = 'https://cdr.pdhc.se/fhir/Encounter'
LOCAL_STATUS_SYSTEM = 'https://request.pdhc.se/fhir/CodeSystem/order-status'

#: R5 ServiceRequest.reason targets.
REASON_TYPES = frozenset({'Condition', 'Observation', 'DiagnosticReport',
                          'DocumentReference', 'DetectedIssue', 'Procedure'})

#: request.pdhc status -> R5 RequestStatus. `archived` is request's own
#: lifecycle end (period over, or every provider done); R5 has no such code,
#: so it is rendered `completed` and keeps its local name in meta.tag.
FHIR_STATUS = {'draft': 'draft', 'active': 'active', 'on-hold': 'on-hold',
               'completed': 'completed', 'revoked': 'revoked',
               'entered-in-error': 'entered-in-error', 'archived': 'completed',
               'unknown': 'unknown'}

STATUS_SV = {'draft': 'utkast', 'active': 'skickad', 'on-hold': 'pausad',
             'completed': 'slutförd', 'revoked': 'makulerad',
             'entered-in-error': 'felregistrerad', 'archived': 'arkiverad',
             'unknown': 'okänd'}

_GUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-'
                   r'[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
_REF = re.compile(r'^(?P<type>[A-Z][A-Za-z]+)/(?P<id>[A-Za-z0-9\-.]{1,64})'
                  r'(/_history/(?P<vid>[A-Za-z0-9\-.]{1,64}))?$')


class JournalFieldInvalid(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def order_identifier(guid):
    return [{'system': IDENTIFIER_SYSTEM, 'value': guid}] if guid else []


def is_guid(value):
    return isinstance(value, str) and bool(_GUID.match(value))


def _ref_string(item, field):
    """A reference given as 'Type/id', {'reference': 'Type/id'} or
    {'reference': {'reference': 'Type/id'}} -> 'Type/id'."""
    if isinstance(item, str):
        ref = item
    elif isinstance(item, dict):
        inner = item.get('reference')
        if isinstance(inner, dict):
            inner = inner.get('reference')
        ref = inner
    else:
        ref = None
    if not isinstance(ref, str) or not _REF.match(ref.strip()):
        raise JournalFieldInvalid(
            f'invalid_{field}',
            f'{field}: each reference must be "Type/<id>" or '
            f'"Type/<id>/_history/<n>", got {item!r}')
    return ref.strip()


def normalise_reason(value):
    """-> R5 CodeableReference[] or None. Each item is {'concept': {...}} with
    a coding or text, or a reference to one of REASON_TYPES."""
    if value in (None, [], ''):
        return None
    if not isinstance(value, list):
        raise JournalFieldInvalid('invalid_reason', 'reason must be a list')
    out = []
    for item in value:
        if isinstance(item, dict) and 'concept' in item:
            concept = item['concept']
            if not isinstance(concept, dict) or not (
                    concept.get('text') or concept.get('coding')):
                raise JournalFieldInvalid(
                    'invalid_reason', 'reason.concept needs text or coding')
            codings = concept.get('coding') or []
            if not isinstance(codings, list) or any(
                    not isinstance(c, dict) or not c.get('code') or not c.get('system')
                    for c in codings):
                raise JournalFieldInvalid(
                    'invalid_reason', 'reason.concept.coding needs system and code')
            out.append({'concept': copy.deepcopy(concept)})
            continue
        ref = _ref_string(item, 'reason')
        rtype = _REF.match(ref).group('type')
        if rtype not in REASON_TYPES:
            raise JournalFieldInvalid(
                'invalid_reason',
                f'reason may reference {", ".join(sorted(REASON_TYPES))}; not {rtype}')
        out.append({'reference': {'reference': ref}})
    return out


def normalise_supporting_info(value):
    """-> list of 'Type/id[/_history/n]' strings, or None."""
    if value in (None, [], ''):
        return None
    if not isinstance(value, list):
        raise JournalFieldInvalid('invalid_supporting_info', 'supporting_info must be a list')
    out = []
    for item in value:
        ref = _ref_string(item, 'supporting_info')
        if ref not in out:
            out.append(ref)
    return out


def normalise_encounter(value):
    if value in (None, ''):
        return None
    if isinstance(value, str) and value.startswith('Encounter/'):
        value = value[len('Encounter/'):]
    if not is_guid(value):
        raise JournalFieldInvalid('invalid_encounter',
                                  'encounter_guid must be a CDR Encounter guid')
    return value.lower()


def normalise_replaces(value):
    if value in (None, [], ''):
        return None
    if not isinstance(value, list):
        raise JournalFieldInvalid('invalid_replaces', 'replaces must be a list of guids')
    out = []
    for item in value:
        g = item[len('ServiceRequest/'):] if isinstance(item, str) and \
            item.startswith('ServiceRequest/') else item
        if not is_guid(g):
            raise JournalFieldInvalid('invalid_replaces',
                                      f'replaces: {item!r} is not a ServiceRequest guid')
        if g not in out:
            out.append(g)
    return out


def reason_or_note_present(src):
    """bestallning-1: reason.exists() or note.exists()."""
    return bool(getattr(src, 'reason', None) or (getattr(src, 'notes', None) or '').strip()
                or getattr(src, 'annotations', None))


def fhir_status(local):
    return FHIR_STATUS.get(local or 'unknown', 'unknown')


def fhir_notes(src):
    notes = []
    text = (getattr(src, 'notes', None) or '').strip()
    if text:
        notes.append({'text': text})
    for a in getattr(src, 'annotations', None) or []:
        if not isinstance(a, dict) or not a.get('text'):
            continue
        n = {'text': a['text']}
        if a.get('time'):
            n['time'] = a['time']
        if a.get('author_guid'):
            n['authorReference'] = {'reference': f"Practitioner/{a['author_guid']}"}
        notes.append(n)
    return notes


def apply_journal_elements(resource, src):
    """Set identifier, reason, encounter, replaces, supportingInfo and note on
    an R5 ServiceRequest dict from `src` (a model or a namespace with the
    same attribute names). Mutates and returns `resource`."""
    guid = getattr(src, 'guid', None)
    resource['identifier'] = order_identifier(guid)
    if getattr(src, 'reason', None):
        resource['reason'] = copy.deepcopy(src.reason)
    else:
        resource.pop('reason', None)
    enc = getattr(src, 'encounter_guid', None)
    if enc:
        resource['encounter'] = {
            'reference': f'Encounter/{enc}',
            'identifier': {'system': ENCOUNTER_IDENTIFIER_SYSTEM, 'value': enc},
        }
    else:
        resource.pop('encounter', None)
    if getattr(src, 'replaces', None):
        resource['replaces'] = [{'reference': f'ServiceRequest/{g}'} for g in src.replaces]
    else:
        resource.pop('replaces', None)
    extra = getattr(src, 'supporting_info', None) or []
    if extra:
        have = {((e.get('reference') or {}).get('reference'))
                for e in resource.get('supportingInfo') or [] if isinstance(e, dict)}
        for ref in extra:
            if ref not in have:
                resource.setdefault('supportingInfo', []).append({'reference': {'reference': ref}})
    notes = fhir_notes(src)
    if notes:
        resource['note'] = notes
    else:
        resource.pop('note', None)
    return resource
