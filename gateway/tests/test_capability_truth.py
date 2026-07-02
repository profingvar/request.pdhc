"""Ticket #372 (rollup #348) — CapabilityStatement truth test.

Rule 20 requires: "test all API endpoints according to the FHIR
terminology capability statement." Rule 9 says "capability statement
must not lie." The pre-#372 `test_all_endpoints.py` file claimed to
exercise every endpoint per the capability statement but was actually
a smoke test with hard-coded route paths — it did not walk the
capability document and so let both #366 (ghost export operation) and
#368 (legacy dispatch operation) survive for weeks.

This module replaces that check. Two directions:

  (a) Every `operation.definition` advertised in /api/v1/metadata
      must resolve to a real route in app.url_map with a compatible
      verb. Catches the ghost-route class of bug directly.

  (b) [DEFERRED] Every non-allowlisted route in app.url_map must be
      advertised somewhere in /api/v1/metadata. request.pdhc has
      many internal-only endpoints (SSO auth callbacks, admin views,
      provider webhook receivers, UI templates) that are legitimately
      not FHIR-shaped; enumerating an allowlist is bigger scope than
      this ticket. Filed as a follow-up under rollup #348.

The extraction reads the FIRST line of `operation.documentation`
(the "METHOD /path — description" convention introduced in #377 when
the CapabilityStatement was made FHIR-R5-conformant — `definition`
must be a canonical URL per the spec, so the raw endpoint moved into
documentation). Both places capability.py declares operations —
`rest.resource[].operation[]` and `rest.operation[]` — use the same
convention.

The extraction does NOT try to infer paths from generic FHIR REST
interactions (`create`/`read`/`update`/`search-type`) because
request.pdhc mixes case (CarePlan resource type → routes at
/careplans lowercase), and guessing the URL from the resource `type`
field would produce false mismatches. Operations, by contrast, have
an unambiguous inline URL on the first line of documentation.
"""
from __future__ import annotations

import re


# The first line of an operation's documentation is required to be
# "METHOD /path" (optionally followed by " — description"). We anchor
# to the start-of-string; anything after the path (including a
# " — description" tail) is trimmed by splitting on the first space.
_DEF_RE = re.compile(r"^(GET|POST|PUT|DELETE|PATCH)\s+(/\S+)")


def _shape(path: str) -> str:
    """Reduce a URL template to shape-only form so
    /api/v1/CarePlan/<guid> matches /api/v1/CarePlan/{id}."""
    # Flask converter syntax: <converter:name> or <name>
    p = re.sub(r"<[^>]+>", "<*>", path)
    # Capability docstring syntax: {name}
    p = re.sub(r"\{[^}]+\}", "<*>", p)
    return p


def _parse_op_first_line(text: str) -> tuple[str, str] | None:
    """Parse the FIRST line of an operation's `documentation` field.

    Convention: `'POST /api/v1/CarePlan/{id}/dispatch — free text'`
    → `('POST', '/api/v1/CarePlan/<*>/dispatch')`. Returns None if
    the first line doesn't start with `METHOD /path`.

    Query strings on the path are stripped — Flask's url_map has
    path patterns only, and documenting `?provider_guid=…&since=…`
    on the capability side is legitimate (helps clients).
    """
    if not text:
        return None
    first_line = text.strip().splitlines()[0].strip()
    m = _DEF_RE.match(first_line)
    if not m:
        return None
    method = m.group(1)
    path = m.group(2).split("?", 1)[0]
    return method, _shape(path)


def _advertised_operations(client) -> set[tuple[str, str]]:
    """Every (METHOD, shaped_path) advertised via an operation entry
    in the CapabilityStatement.

    Sources: `rest[0].resource[].operation[]` and
    `rest[0].operation[]`.
    """
    body = client.get("/api/v1/metadata").get_json()
    rest = body["rest"][0]
    out: set[tuple[str, str]] = set()

    for res in rest.get("resource", []):
        for op in res.get("operation", []) or []:
            parsed = _parse_op_first_line(op.get("documentation", ""))
            if parsed:
                out.add(parsed)

    for op in rest.get("operation", []) or []:
        parsed = _parse_op_first_line(op.get("documentation", ""))
        if parsed:
            out.add(parsed)

    return out


def _url_map_shapes(app) -> set[tuple[str, str]]:
    """Every (METHOD, shaped_path) rule in app.url_map, skipping
    HEAD/OPTIONS (which Flask auto-adds for every GET rule)."""
    out: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        methods = (rule.methods or set()) - {"HEAD", "OPTIONS"}
        for m in methods:
            out.add((m, _shape(rule.rule)))
    return out


class TestCapabilityTruth:
    """Direction (a) — every advertised operation is a real route."""

    def test_first_line_regex_matches(self):
        """Sanity — the METHOD/path regex still parses the shape
        `POST /api/v1/foo — description` correctly."""
        assert _parse_op_first_line("POST /api/v1/foo — bar baz") == (
            "POST", "/api/v1/foo"
        )
        assert _parse_op_first_line("GET /api/v1/x/<*>/y") == (
            "GET", "/api/v1/x/<*>/y"
        )
        # Query strings stripped.
        assert _parse_op_first_line("GET /api/v1/x?a=<*>") == (
            "GET", "/api/v1/x"
        )
        assert _parse_op_first_line("not a documented endpoint") is None
        assert _parse_op_first_line("") is None
        assert _parse_op_first_line(None) is None

    def test_metadata_endpoint_is_reachable(self, client):
        """Sanity — /api/v1/metadata must respond 200 so the
        rest of the tests can even run."""
        resp = client.get("/api/v1/metadata")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("resourceType") == "CapabilityStatement"

    def test_every_advertised_operation_resolves_in_url_map(self, app, client):
        advertised = _advertised_operations(client)
        assert advertised, (
            "extracted zero operations from CapabilityStatement — "
            "either capability.py stopped shipping definitions or "
            "_parse_op_definition drifted from the format."
        )
        url_map = _url_map_shapes(app)
        missing = advertised - url_map
        assert not missing, (
            f"CapabilityStatement advertises {len(missing)} operation(s) "
            f"with no matching route in app.url_map:\n  "
            + "\n  ".join(f"{m} {p}" for m, p in sorted(missing))
            + "\n\nEither (i) the route was renamed/deleted without "
            "updating capability.py (ghost route), or (ii) the "
            "definition string in capability.py has drifted from a "
            "real url_map rule shape."
        )

    def test_no_stale_careplan_export_or_legacy_dispatch(self, client):
        """Regression guard for #366 + #368 — the ghost operations
        that made this test suite necessary must not come back."""
        advertised = _advertised_operations(client)
        stale = [
            (m, p) for m, p in advertised
            if p.startswith("/api/v1/CarePlan/") and (
                p.endswith("/export/csv") or p.endswith("/dispatch")
            )
        ]
        assert not stale, (
            f"pre-#366/#368 stale CarePlan operations re-introduced in "
            f"capability.py: {stale}. These were deleted alongside the "
            "code they pointed at; do not resurrect them."
        )
