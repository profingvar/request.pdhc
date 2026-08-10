# Medituner AB — provider onboarding email (asthma home-monitoring)

Ready-to-send onboarding instructions for Medituner AB to begin reporting
observations against the asthma home-monitoring ServiceRequest.

**Security note — this file contains NO credentials.** The Provider Access
Token (PAT) and the grant token are secrets and are handed to the provider
out-of-band on **two separate channels**, never in the same message and never
committed to this repo. The placeholders below mark where they slot in.

**Live identifiers (as of 2026-08-10):**

| Item | Value |
|---|---|
| ServiceRequest | `4b8598b0-d857-4ba5-bc66-925972206cba` (active) |
| Contract | `b23c8bec-b0f5-4acc-86f8-090fa075a234` (executed, UAS ↔ Medituner AB) |
| Provider org (Medituner AB) | `7a69ab02-dfce-43ae-ade7-fabf6b858d84` |
| PAT guid | `db5d94c7-84e2-47ca-be97-aef83af8c858` (poll mode, expires 2026-11-08) |
| Grant guid | `8e036e3a-188a-4bcd-8d6f-a2dc6c7f7c57` (expires 2026-11-08) |

The pipeline (report → gateway validate + concept-resolve → CdrDeliveryLog →
forwarder → cdr1) was validated end-to-end on 2026-08-10.

---

**To:** Marcus — Medituner AB
**Subject:** PDHC integration — asthma home-monitoring go-live: endpoint, credentials & payload spec

Hi Marcus,

The contract (*UAS ↔ Medituner AB, asthma home-monitoring*) is executed and the
service request is active on our side, so we're ready to receive data.
Everything you need to start reporting observations is below.

**1. Credentials** (sent to you separately, on two different channels — please
don't store them together):
- **Provider Access Token (PAT)** → sent via channel 1. Send it as the
  `X-Provider-Token` HTTP header on every request.
- **Grant token** → sent via channel 2. Include it in the JSON body as
  `grant_token`.
- Both are valid until **2026-11-08**. Ping us before then and we'll rotate.

**2. Endpoint** (TLS only):
```
POST https://gateway.pdhc.se/api/v1/provider/report/4b8598b0-d857-4ba5-bc66-925972206cba
```
The service-request GUID in the path (`4b8598b0-…`) identifies this patient's
asthma plan — keep it fixed for all reports on this request.

**3. Request format**
```
Headers:
  X-Provider-Token: <PAT from channel 1>
  Content-Type: application/json
  X-Correlation-Id: <your own id, optional but recommended>

Body:
{
  "grant_token": "<grant token from channel 2>",
  "status": "in-progress",
  "report_payload": {
    "observations": [
      { "transaction_guid": "6521528c-db59-45c5-a492-003c28f27623", "value": 3.1,   "recorded_at": "2026-08-11T08:00:00Z" },
      { "transaction_guid": "8baad6ac-486d-4428-ab37-9f971f43fd71", "value": 420,   "recorded_at": "2026-08-11T08:00:00Z" },
      { "transaction_guid": "45870f77-ce44-4ebb-85d0-b9af5917504f", "value": false, "recorded_at": "2026-08-11T08:00:00Z" }
    ]
  }
}
```
- Put the **concept GUID** in `transaction_guid`; send only `value` +
  `recorded_at` (ISO-8601 UTC). We derive concept, unit and ranges
  authoritatively from the plan — you don't need to send them.
- **`status`**: use `"in-progress"` for ongoing daily/weekly reports; send
  `"completed"` on the final report when the monitoring window closes.
- You may batch several observations in one call. Re-sending the same
  `(patient, concept, recorded_at)` is safe — we de-duplicate, so retries won't
  create duplicates.

**4. Concepts you may report** (all in the contract's return scope):

| Concept | GUID | Value to send |
|---|---|---|
| FEV1 (weekly spirometry) | `6521528c-db59-45c5-a492-003c28f27623` | number, litres |
| Peak flow (PEF) | `8baad6ac-486d-4428-ab37-9f971f43fd71` | number, L/min |
| SpO₂ | `2f15ae94-209e-4b0c-81bd-c91d76e74475` | number, % |
| Daytime symptoms | `15cedab1-f694-467d-96dc-ad9bbd5794db` | number (scale) |
| Breathlessness | `0139525f-fbc7-427e-a508-cf33c4c681eb` | number (0–10) |
| Activity limitation | `e3d8cf4f-81e1-4046-8e9a-3a371725df05` | number (0–10) |
| Night waking | `6f6fbe8d-4e7e-4989-984a-b6d2b0ebcac4` | integer (count) |
| Reliever use | `89864ae4-012f-4d62-9cb8-ac15ab66e6c4` | integer (puffs/day) |
| Controller taken | `0c15ab68-5c79-4a35-a123-60fb69e64cf3` | boolean (`true`/`false`) |
| Wheeze | `45870f77-ce44-4ebb-85d0-b9af5917504f` | boolean (`true`/`false`) |

Send a JSON **number** for numeric/integer/scale items and a JSON **boolean**
(`true`/`false`) for the two yes/no items. Concepts outside this list will be
rejected.

**5. Responses & receipts**
- On success you'll get **HTTP 202** with
  `{"status":"accepted","observations_stored":N,"receipt_guid":"…"}`.
  Rejections come back as 4xx with a `code` and detail (e.g. `SCOPE_VIOLATION`,
  `VALIDATION_ERROR`).
- For asynchronous **delivery receipts**, please send us (a) a receiver URL and
  (b) a shared secret. We'll then push HMAC-signed receipts to that URL. Until
  you provide those, your token is in **poll** mode — you can fetch status from
  `GET /api/v1/provider/feed` instead.

**6. Before you start**
- Confirm your systems can reach `https://gateway.pdhc.se` over TLS.
- Send us your receiver URL + secret whenever ready (item 5).
- A single test observation is enough for us to confirm the round-trip
  end-to-end.

We've validated this exact path on our side, so once you've loaded the two
credentials you should be able to POST straight away. Any questions, reply here.

Best regards,
PDHC Integration — pdhc.se
