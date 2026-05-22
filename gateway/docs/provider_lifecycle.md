# Provider lifecycle (PAT + webhook signing secret)

Ticket #136. Each provider organisation carries two independent
credentials in request.pdhc:

1. **Provider Access Token (PAT)** — bearer token sent on every
   inbound provider call. Hashed (bcrypt) at rest.
2. **Webhook signing secret** — symmetric HMAC key used by the
   dispatcher (#140) to sign outbound webhook bodies. Fernet-encrypted
   at rest.

Both have a three-state lifecycle: `active` → `deprecated` → `revoked`.
Rotation marks the previous credential as `deprecated` and keeps it
accepted for `PAT_DEPRECATED_GRACE_DAYS` (default 14) so providers can
swap at their own pace without an outage window. `revoked` takes
effect immediately.

## Provider Access Token

Backing model: `ProviderAccessToken` in `app/models/security_models.py`.

Columns relevant to lifecycle:

| Column | Meaning |
|---|---|
| `status` | `active` / `deprecated` / `revoked` (ticket #136). |
| `revoked` | Legacy boolean — kept in sync with `status='revoked'` for back-compat. |
| `expires_at` | Hard expiry, set at issue. |
| `deprecated_at` | When `status` flipped to `deprecated`. Drives grace-period math. |
| `rotated_to_guid` | GUID of the new PAT that replaced this one. |

`is_valid()` accepts active PATs and deprecated PATs whose
`deprecated_at + grace_days` has not passed; otherwise rejects.
Legacy `revoked=True` rows are also rejected — covers DB rows mutated
by older code that didn't update `status`.

`validate_pat(raw_token)` filters out hard-revoked rows up front and
bcrypt-compares the remainder. On match, applies `is_valid()`.

## Webhook signing secret

Backing model: `WebhookSigningSecret`. Per provider org, not per
contract — a provider has one signing identity regardless of how many
contracts they participate in.

Plaintext storage:

- `WEBHOOK_SECRETS_KEY` env var holds a Fernet key (32 bytes,
  URL-safe base64). Generate with
  `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
- Plaintext is encrypted with that key and stored in
  `secret_encrypted`. Service-level helpers (`_encrypt` / `_decrypt`)
  are the only callers.
- The plaintext is returned by `register_secret` / `rotate_secret`
  exactly once — it cannot be recovered later. Operators write it
  down (1Password / secure handover) and ship it to the provider out
  of band.

Future migration path: when KMS is available, swap `_fernet()` to
return a KMS-backed key handle. `secret_encrypted` is a Text column,
so the new ciphertext fits without a schema change.

`is_valid_for_signing()` — only `status='active'` (outbound signatures
never use a deprecated secret).

`is_valid_for_verification()` — active and grace-period deprecated
both accepted (so inbound replies signed against the previous secret
are still verifiable during the rotation window).

## CLI

All under the `flask provider` group:

```bash
# Issue a brand-new PAT
flask provider register-pat \
  --org-guid <provider-org-guid> \
  --contract-guid <contract-guid> \
  --scopes read,write \
  --delivery-mode push \
  --push-endpoint-url https://example.com/webhook \
  --expires-days 365

# Rotate (issue new active, mark old deprecated)
flask provider rotate-pat \
  --org-guid <provider-org-guid> \
  --contract-guid <contract-guid>

# Revoke a specific PAT immediately
flask provider revoke-pat --pat-guid <pat-guid>

# Issue first webhook signing secret for an org
flask provider register-signing-secret --org-guid <provider-org-guid>

# Rotate the signing secret
flask provider rotate-signing-secret --org-guid <provider-org-guid>

# Revoke every signing secret for an org (active + deprecated)
flask provider revoke-signing-secret --org-guid <provider-org-guid>
```

Every command emits the new credential **once** on stdout. Treat
stdout as sensitive.

## Audit

Every lifecycle event writes an entry via `audit_service.log_event`:

| Action | Resource | Notes |
|---|---|---|
| `pat.issued` | `ProviderAccessToken` | Includes scopes + delivery_mode. |
| `pat.rotated` | `ProviderAccessToken` | New + previous GUIDs. |
| `pat.revoked` | `ProviderAccessToken` | provider_org_guid. |
| `webhook_secret.issued` | `WebhookSigningSecret` | provider_org_guid. |
| `webhook_secret.rotated` | `WebhookSigningSecret` | new + previous GUIDs. |
| `webhook_secret.revoked` | `WebhookSigningSecret` | revoked_count. |

## Configuration

| Env | Default | Notes |
|---|---|---|
| `WEBHOOK_SECRETS_KEY` | (required to register/rotate secrets) | Fernet key. |
| `PAT_DEPRECATED_GRACE_DAYS` | `14` | How long a deprecated PAT remains accepted post-rotation. |
| `PAT_DEFAULT_EXPIRY_DAYS` | `365` | Default hard expiry. |

## Migration

Alembic revision `d4e5f6a7b8c9`
(`d4e5f6a7b8c9_provider_three_state_status_and_webhook_secrets.py`)
adds the new columns + table. Backfill: existing PAT rows with
`revoked=True` get `status='revoked'`. Run via
`flask db upgrade` from the gateway directory.
