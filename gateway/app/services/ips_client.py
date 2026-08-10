"""Client for ips.pdhc — spärr (PatientBlock) visibility for SR read paths.

Ticket #228 / request.pdhc PDL #4. Consults ips.pdhc's cross-service block
predicate to decide whether a ServiceRequest row may be shown.

What this filters:
  - SR list and SR detail: a ServiceRequest is hidden / 404'd when its
    patient has an active clinic-scope block whose ``source_scope_id``
    matches the SR's ``requester_org_guid``. Rationale: the SR row itself
    reveals that the patient was the subject of a service request from that
    org — exposing it would let the blocked org learn what it should not see.

Transport (2026-08-10, spärr auth fix): this uses ips.pdhc's purpose-built
``GET /api/v1/patients/<pid>/blocks/check?source_clinic_id=<org>`` predicate,
authenticated with ``Authorization: ApiKey <key>``. That endpoint is
explicitly documented as requiring *no* patient-clinic relationship ("must
work for callers who don't yet have a relationship to the patient — precisely
the case the spärr is protecting against"), returns un-redacted
``is_blocked`` + ``blocking_scopes`` (with lift info), and applies the
clinic-vs-caregiver scope match server-side. The previous implementation sent
the key as ``X-API-Key`` (ips reads only ``Authorization``) and called the
staff ``/blocks`` list endpoint (clinic-gated + source_scope_id redaction), so
every call 401'd and the filter silently failed open — no SR was ever hidden.

Caregiver-scope blocks (#204) are v2 and deliberately ignored here: we pass
only ``source_clinic_id``, so check_block never matches a caregiver block.

Webhook-driven invalidation (IPS Renov 6 / #202) plugs into
``invalidate(patient_guid)``; until #202 ships the cache is bounded by TTL
alone (legal-confirmed 2026-06-04 as acceptable).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable

import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers


DEFAULT_TTL_SECONDS = 30
DEFAULT_TIMEOUT = 4.0


@dataclass(frozen=True)
class SprCheck:
    """Result of a spärr predicate for one (patient, requester_org) pair."""
    is_blocked: bool
    scopes: tuple  # tuple of blocking_scope dicts from ips /blocks/check

    @property
    def has_lift(self) -> bool:
        """True iff any matching scope carries a lift. Under the v1 SR rule a
        lift on the blocked scope EXPOSES the SR row (the per-observation
        mechanical filter then applies downstream #205/#206/#207)."""
        return any(s.get("lift_kind") for s in self.scopes)


class IpsClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.api_key = api_key
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self.api_key:
            # ips.pdhc require_auth reads ONLY the Authorization header and
            # accepts the "ApiKey <raw>" scheme (services/auth_service.py).
            h["Authorization"] = f"ApiKey {self.api_key}"
        h.update(outbound_session_headers())
        return h

    def check_block(self, patient_guid: str, source_clinic_id: str):
        """Ask ips whether ``source_clinic_id`` is blocked for ``patient_guid``.

        Returns ``(is_blocked: bool, scopes: list[dict])``. On a genuine error
        (network, 4xx/5xx, patient unknown → 404) returns ``(False, [])`` —
        fail-open, but now only on real errors rather than on every call.
        """
        if not self.base_url or not patient_guid or not source_clinic_id:
            return (False, [])
        url = f"{self.base_url}/api/v1/patients/{patient_guid}/blocks/check"
        try:
            r = requests.get(
                url, params={"source_clinic_id": source_clinic_id},
                headers=self._headers(), timeout=self.timeout,
            )
        except requests.RequestException:
            current_app.logger.warning(
                "ips block check failed (network) for %s", patient_guid[:12],
            )
            return (False, [])
        if r.status_code == 404:
            # Patient not known to ips → no blocks.
            return (False, [])
        if r.status_code >= 400:
            current_app.logger.warning(
                "ips block check %s -> %s", patient_guid[:12], r.status_code
            )
            return (False, [])
        payload = r.json() or {}
        return (bool(payload.get("is_blocked")),
                list(payload.get("blocking_scopes") or []))


class _CheckCache:
    """TTL cache keyed by ``"<patient>|<org>"``."""

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, SprCheck]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(patient_guid: str, org_guid: str) -> str:
        return f"{patient_guid}|{org_guid}"

    def get(self, patient_guid: str, org_guid: str) -> SprCheck | None:
        with self._lock:
            entry = self._data.get(self._key(patient_guid, org_guid))
            if not entry or time.monotonic() >= entry[0]:
                self.misses += 1
                return None
            self.hits += 1
            return entry[1]

    def put(self, patient_guid: str, org_guid: str, chk: SprCheck) -> None:
        with self._lock:
            self._data[self._key(patient_guid, org_guid)] = (
                time.monotonic() + self.ttl, chk)

    def invalidate(self, patient_guid: str | None = None) -> None:
        with self._lock:
            if patient_guid is None:
                self._data.clear()
            else:
                # Composite keys → evict every (patient, *) entry.
                prefix = f"{patient_guid}|"
                for k in [k for k in self._data if k.startswith(prefix)]:
                    self._data.pop(k, None)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total) if total else 0.0
            return {
                "hits": self.hits, "misses": self.misses,
                "hit_rate": hit_rate, "size": len(self._data),
            }


_cache = _CheckCache()


def invalidate(patient_guid: str | None = None) -> None:
    """Webhook entry point for IPS Renov 6 / #202."""
    _cache.invalidate(patient_guid)


def cache_stats() -> dict:
    return _cache.stats()


def _default_client() -> IpsClient:
    return IpsClient(
        api_key=current_app.config.get("IPS_API_KEY") or None,
        base_url=current_app.config.get("IPS_BASE_URL") or None,
    )


def get_sr_check(
    patient_guid: str,
    requester_org_guid: str,
    *,
    client: IpsClient | None = None,
    use_cache: bool = True,
) -> SprCheck:
    """Cached spärr predicate for one (patient, requester_org) pair."""
    if not patient_guid or not requester_org_guid:
        return SprCheck(is_blocked=False, scopes=())
    if use_cache:
        cached = _cache.get(patient_guid, requester_org_guid)
        if cached is not None:
            return cached
    client = client or _default_client()
    is_blocked, scopes = client.check_block(patient_guid, requester_org_guid)
    chk = SprCheck(is_blocked=is_blocked, scopes=tuple(scopes))
    if use_cache:
        _cache.put(patient_guid, requester_org_guid, chk)
    return chk


def is_sr_visible(sr, *, client: IpsClient | None = None) -> bool:
    """True iff a single SR row passes the spärr filter.

    Hidden iff the patient has an active clinic-scope block on the SR's
    ``requester_org_guid`` with no lift. A lift on that scope exposes the SR
    (the per-observation mechanical filter applies downstream where the
    observations are actually returned — dashboard #205, gateway #206,
    cdr_6 #207).
    """
    patient = getattr(sr, "patient_guid", None)
    requester_org = getattr(sr, "requester_org_guid", None)
    if not patient or not requester_org:
        return True
    chk = get_sr_check(patient, requester_org, client=client)
    if not chk.is_blocked:
        return True
    return chk.has_lift


def filter_visible_srs(srs: list, *, client: IpsClient | None = None) -> list:
    """Apply the spärr filter to a list of SRs; return the visible subset.

    One cached ips lookup per unique (patient_guid, requester_org_guid).
    """
    return [sr for sr in srs if is_sr_visible(sr, client=client)]
