"""Client for ips.pdhc — fetch active spärr (PatientBlock) entries.

Ticket #228 / request.pdhc PDL #4. Mirrors the gateway.pdhc client
(spärr Phase 3 #206) — same 30 s TTL cache, same indispensable-care
mechanical-filter — adapted for request.pdhc's ServiceRequest read
paths.

What this filters:
  - SR list and SR detail: a ServiceRequest is hidden / 404'd when its
    patient has an active block whose ``source_scope_id`` matches the
    SR's ``requester_org_guid``. Rationale: the SR row itself reveals
    that the patient was the subject of a service request from that
    org — exposing it would let the blocked org learn what it should
    not see.

Webhook-driven invalidation (IPS Renov 6 / #202) plugs into
``invalidate(patient_guid)``; until #202 ships the cache is bounded
by TTL alone (legal-confirmed 2026-06-04 as acceptable).
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
class Block:
    guid: str
    patient_guid: str
    source_scope_type: str
    source_scope_id: str
    is_active: bool
    lift_kind: str | None
    lift_concept_guids: list | None
    lift_from_date: str | None
    lift_until_date: str | None

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            guid=str(d.get("guid")),
            patient_guid=str(d.get("patient_guid")),
            source_scope_type=d.get("source_scope_type") or "clinic",
            source_scope_id=str(d.get("source_scope_id")),
            is_active=bool(d.get("is_active")),
            lift_kind=d.get("lift_kind"),
            lift_concept_guids=d.get("lift_concept_guids"),
            lift_from_date=d.get("lift_from_date"),
            lift_until_date=d.get("lift_until_date"),
        )


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
            h["X-API-Key"] = self.api_key
        h.update(outbound_session_headers())
        return h

    def fetch_active_blocks(self, patient_guid: str) -> list[Block]:
        if not self.base_url or not patient_guid:
            return []
        url = f"{self.base_url}/api/v1/patients/{patient_guid}/blocks"
        try:
            r = requests.get(
                url, params={"active": "true"},
                headers=self._headers(), timeout=self.timeout,
            )
        except requests.RequestException:
            current_app.logger.warning(
                "ips block fetch failed (network) for %s", patient_guid[:12],
            )
            return []
        if r.status_code == 404:
            return []
        if r.status_code >= 400:
            current_app.logger.warning(
                "ips block fetch %s -> %s", patient_guid[:12], r.status_code
            )
            return []
        payload = r.json() or {}
        raw = payload.get("blocks") or payload.get("entry") or []
        return [Block.from_dict(b) for b in raw if isinstance(b, dict)]


class _BlockCache:
    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS):
        self.ttl = ttl
        self._lock = threading.Lock()
        self._data: dict[str, tuple[float, list[Block]]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, patient_guid: str) -> list[Block] | None:
        with self._lock:
            entry = self._data.get(patient_guid)
            if not entry or time.monotonic() >= entry[0]:
                self.misses += 1
                return None
            self.hits += 1
            return entry[1]

    def put(self, patient_guid: str, blocks: list[Block]) -> None:
        with self._lock:
            self._data[patient_guid] = (time.monotonic() + self.ttl, blocks)

    def invalidate(self, patient_guid: str | None = None) -> None:
        with self._lock:
            if patient_guid is None:
                self._data.clear()
            else:
                self._data.pop(patient_guid, None)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total) if total else 0.0
            return {
                "hits": self.hits, "misses": self.misses,
                "hit_rate": hit_rate, "size": len(self._data),
            }


_cache = _BlockCache()


def invalidate(patient_guid: str | None = None) -> None:
    """Webhook entry point for IPS Renov 6 / #202."""
    _cache.invalidate(patient_guid)


def cache_stats() -> dict:
    return _cache.stats()


def get_active_blocks(
    patient_guid: str,
    *,
    client: IpsClient | None = None,
    use_cache: bool = True,
) -> list[Block]:
    if not patient_guid:
        return []
    if use_cache:
        cached = _cache.get(patient_guid)
        if cached is not None:
            return cached
    client = client or _default_client()
    blocks = [b for b in client.fetch_active_blocks(patient_guid) if b.is_active]
    if use_cache:
        _cache.put(patient_guid, blocks)
    return blocks


def _default_client() -> IpsClient:
    return IpsClient(
        api_key=current_app.config.get("IPS_API_KEY") or None,
        base_url=current_app.config.get("IPS_BASE_URL") or None,
    )


def fetch_blocks_for_patients(
    patient_guids: Iterable[str],
    *,
    client: IpsClient | None = None,
) -> dict[str, list[Block]]:
    """Batched + de-duped per-patient fetch."""
    out: dict[str, list[Block]] = {}
    seen: set[str] = set()
    for pid in patient_guids:
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out[pid] = get_active_blocks(pid, client=client)
    return out


# ---------------------------------------------------------------------------
# Filter helpers
# ---------------------------------------------------------------------------


def blocked_clinic_ids(blocks: Iterable[Block]) -> set[str]:
    """Active clinic-scope source ids. Caregiver-scope blocks are v2
    (#204) and ignored here."""
    return {
        b.source_scope_id
        for b in blocks
        if b.is_active and b.source_scope_type == "clinic"
    }


def is_sr_visible(sr, blocks: Iterable[Block]) -> bool:
    """True iff a single SR row passes the spärr filter.

    Rule: an SR is hidden iff its patient has an active clinic-scope
    block whose ``source_scope_id`` matches the SR's
    ``requester_org_guid``. The SR row reveals that the patient was the
    subject of a service request from that org — the same privacy
    boundary as the underlying observation read.

    indispensable_care lifts: the mechanical filter applies on concept
    + date, but an SR is plan-level, not concept-level — the SR itself
    doesn't carry a single concept_guid. Conservative v1 interpretation:
    a lift on the same scope EXPOSES the SR (lifted clinics can see the
    SR), regardless of which concepts are in the lift's filter. The
    per-row mechanical filter then applies downstream where observations
    are actually returned (dashboard #205, gateway #206, cdr_6 #207).
    """
    blocked = blocked_clinic_ids(blocks)
    requester_org = getattr(sr, "requester_org_guid", None)
    if requester_org not in blocked:
        return True
    # Active block hits this requester; check for any lift on this scope.
    for b in blocks:
        if (
            b.source_scope_id == requester_org
            and b.source_scope_type == "clinic"
            and b.lift_kind is not None
        ):
            return True
    return False


def filter_visible_srs(srs: list, blocks_by_patient: dict) -> list:
    """Apply spärr filter to a list of SRs. Returns the visible subset.

    ``blocks_by_patient``: ``{patient_guid: [Block...]}`` — caller
    batches one IPS lookup per unique patient_guid in the result set.
    """
    out = []
    for sr in srs:
        pid = getattr(sr, "patient_guid", None)
        blocks = blocks_by_patient.get(pid) or []
        if is_sr_visible(sr, blocks):
            out.append(sr)
    return out
