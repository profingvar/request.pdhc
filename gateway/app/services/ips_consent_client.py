"""Client for ips.pdhc consent surface — IPS Renov 2 (#198) consumer.

Mirrors ``services/ips_client.py`` (the block-check path) — same 30 s TTL
cache, same invalidation hook — adapted for the ``PatientConsent`` resource.

Transport (2026-08-10, #558): consults ips.pdhc's cross-service predicate
``GET /api/v1/patients/<pid>/consents/check?grantee_caregiver_guid=<cg>``,
authenticated with ``Authorization: ApiKey <key>``. That endpoint requires no
patient-clinic relationship (the exact mirror of ``/blocks/check``) and
returns only the ACTIVE consents naming the asking caregiver. The previous
implementation sent the key as ``X-API-Key`` (ips reads only ``Authorization``)
and hit the clinic-gated ``/consents`` list — so every call 401'd, the empty
result flowed into ``consent_covers_dispatch``, and any cross-caregiver
dispatch was refused fail-closed (reason ``no_consent``).

What this enforces (Lag 2022:913 § 5):
  - Dispatch crosses caregivers; the destination caregiver must hold
    a valid (granted, not revoked, not expired) consent from the
    patient before request.pdhc forwards the dispatch upstream.
  - When the patient narrowed the consent to specific concepts, the
    dispatch's payload concept must be in that set; otherwise refuse.

What this does NOT do:
  - Resolve organisation -> caregiver mapping. Callers supply
    ``destination_caregiver_guid`` directly; the SSO Phase 1 #188
    ``organization_caregivers`` blob field lets a UI compute the
    caregiver for an org without a second SSO call.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

import requests
from flask import current_app

from app.services.session_headers import outbound_session_headers


DEFAULT_TTL_SECONDS = 30
DEFAULT_TIMEOUT = 4.0


@dataclass(frozen=True)
class Consent:
    guid: str
    patient_guid: str
    grantee_caregiver_guid: str
    consented_concept_guids: Optional[Sequence[str]]
    is_active: bool

    @classmethod
    def from_dict(cls, d: dict) -> "Consent":
        cg = d.get("consented_concept_guids")
        return cls(
            guid=str(d.get("guid")),
            patient_guid=str(d.get("patient_guid")),
            grantee_caregiver_guid=str(d.get("grantee_caregiver_guid")),
            consented_concept_guids=(
                [str(c) for c in cg] if isinstance(cg, list) else None
            ),
            is_active=bool(d.get("is_active")),
        )


class IpsConsentClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
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

    def fetch_consents_for_grantee(
        self, patient_guid: str, grantee_caregiver_guid: str,
    ) -> list[Consent]:
        """Active consents from ``patient_guid`` to ``grantee_caregiver_guid``
        via ips /consents/check. On any error / 404 returns [] (fail-open on
        genuine errors only — but note the dispatch gate then fails CLOSED,
        because zero consents means 'no_consent')."""
        if not self.base_url or not patient_guid or not grantee_caregiver_guid:
            return []
        url = (
            f"{self.base_url}/api/v1/patients/{patient_guid}/consents/check"
        )
        try:
            r = requests.get(
                url,
                params={"grantee_caregiver_guid": grantee_caregiver_guid},
                headers=self._headers(), timeout=self.timeout,
            )
        except requests.RequestException:
            current_app.logger.warning(
                "ips consent check failed (network) for %s",
                patient_guid[:12] if patient_guid else "?",
            )
            return []
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            current_app.logger.warning(
                "ips consent check %s -> %s",
                patient_guid[:12] if patient_guid else "?",
                r.status_code,
            )
            return []
        payload = r.json() or {}
        raw = payload.get("consents") or []
        return [
            Consent.from_dict(c) for c in raw if isinstance(c, dict)
        ]


class _ConsentCache:
    """TTL cache keyed by ``"<patient>|<grantee>"``."""

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, list[Consent]]] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(patient_guid: str, grantee_guid: str) -> str:
        return f"{patient_guid}|{grantee_guid}"

    def get(self, patient_guid: str, grantee_guid: str) -> Optional[list[Consent]]:
        with self._lock:
            entry = self._data.get(self._key(patient_guid, grantee_guid))
            if not entry or time.monotonic() >= entry[0]:
                self.misses += 1
                return None
            self.hits += 1
            return entry[1]

    def put(self, patient_guid: str, grantee_guid: str,
            consents: list[Consent]) -> None:
        with self._lock:
            self._data[self._key(patient_guid, grantee_guid)] = (
                time.monotonic() + self.ttl, consents,
            )

    def invalidate(self, patient_guid: Optional[str] = None) -> None:
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


_cache = _ConsentCache()


def invalidate(patient_guid: Optional[str] = None) -> None:
    """Webhook entry point (parity with block invalidation)."""
    _cache.invalidate(patient_guid)


def cache_stats() -> dict:
    return _cache.stats()


def _default_client() -> IpsConsentClient:
    return IpsConsentClient(
        api_key=current_app.config.get("IPS_API_KEY") or None,
        base_url=current_app.config.get("IPS_BASE_URL") or None,
    )


def get_active_consents(
    patient_guid: str,
    grantee_caregiver_guid: str,
    *,
    client: Optional[IpsConsentClient] = None,
    use_cache: bool = True,
) -> list[Consent]:
    """Active consents from ``patient_guid`` to ``grantee_caregiver_guid``,
    cached per (patient, grantee)."""
    if not patient_guid or not grantee_caregiver_guid:
        return []
    if use_cache:
        cached = _cache.get(patient_guid, grantee_caregiver_guid)
        if cached is not None:
            return cached
    client = client or _default_client()
    consents = [
        c for c in client.fetch_consents_for_grantee(
            patient_guid, grantee_caregiver_guid)
        if c.is_active
    ]
    if use_cache:
        _cache.put(patient_guid, grantee_caregiver_guid, consents)
    return consents


# ---------------------------------------------------------------------------
# Decision helpers
# ---------------------------------------------------------------------------


def consent_covers_dispatch(
    consents: Iterable[Consent],
    *,
    destination_caregiver_guid: str,
    payload_concept_guids: Optional[Sequence[str]] = None,
) -> tuple[bool, Optional[str]]:
    """Return (ok, reason) for whether the consents cover this dispatch.

    Rules:
      1. At least one ACTIVE consent must name
         ``destination_caregiver_guid`` as grantee. Otherwise refuse
         with reason 'no_consent'.
      2. Whole-caregiver consent (``consented_concept_guids is None``)
         covers any payload — accept.
      3. Concept-narrowed consent covers only the listed concepts. If
         ``payload_concept_guids`` is supplied and any payload concept
         is outside the union of concept lists across active consents
         to this caregiver, refuse with reason 'concept_not_consented'.
      4. ``payload_concept_guids = None`` skips the concept check (the
         caller didn't tell us what concepts are in the payload) —
         caregiver-level consent alone is enough.
    """
    if not destination_caregiver_guid:
        return False, "no_destination_caregiver"
    relevant = [
        c for c in consents
        if c.is_active
        and c.grantee_caregiver_guid == destination_caregiver_guid
    ]
    if not relevant:
        return False, "no_consent"

    if any(c.consented_concept_guids is None for c in relevant):
        # At least one whole-caregiver grant -> unrestricted.
        return True, None

    if not payload_concept_guids:
        # Concept-narrowed grants only, but caller didn't supply
        # payload concepts to check against. Accept on the caregiver
        # level alone — narrowed grants are still a yes to the
        # caregiver; the concept boundary is enforced downstream
        # where data is actually read (cdr_6, dashboard).
        return True, None

    allowed = set()
    for c in relevant:
        for g in c.consented_concept_guids or []:
            allowed.add(g)
    missing = [g for g in payload_concept_guids if g not in allowed]
    if missing:
        return False, "concept_not_consented"
    return True, None
