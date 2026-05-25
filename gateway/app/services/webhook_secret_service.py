"""Webhook signing-secret service (ticket #136).

Per provider org, manages a Fernet-encrypted HMAC secret used by the
dispatcher (#140) to sign outbound webhook bodies. The plaintext is
shown ONCE when register/rotate is invoked; it is never logged and
cannot be recovered later.

Lifecycle:
- `register_secret(org_guid)` — first-time secret for an org. Fails if
  one already exists in active state (use rotate instead).
- `rotate_secret(org_guid)` — issue a new active secret; mark the
  previous active one 'deprecated' with `deprecated_at = now()`.
- `revoke_secret(org_guid)` — mark every secret for the org as revoked
  (active + deprecated). Takes effect immediately.
- `get_signing_secret(org_guid)` — returns the plaintext of the
  currently-active secret. For dispatcher use only.
- `get_verification_secrets(org_guid)` — list of plaintexts (active +
  grace-period deprecated). For inbound webhook verification.

Storage uses Fernet (cryptography lib) with key from env
`WEBHOOK_SECRETS_KEY` (32-byte URL-safe base64).
"""
import logging
import os
import secrets

from cryptography.fernet import Fernet, InvalidToken
from datetime import datetime, timezone

from app import db
from app.models.security_models import WebhookSigningSecret
from app.services.audit_service import log_event

logger = logging.getLogger(__name__)


SECRET_BYTES = 48  # 384 bits — comfortable margin for HMAC-SHA256


# Fernet plumbing moved to the shared secret_crypto module (#151) so the
# webhook signing-secret and the PAT push_auth_key share one key + scheme.
# Imported under the original private names so the rest of this module is
# unchanged.
from app.services.secret_crypto import encrypt as _encrypt, decrypt as _decrypt


def _generate_secret():
    """Generate a fresh URL-safe high-entropy secret."""
    return secrets.token_urlsafe(SECRET_BYTES)


def register_secret(provider_org_guid, *, created_by_user_guid,
                    ip_address=None):
    """Issue a first signing secret for a provider org.

    Returns (result_dict_with_plaintext, status_code).
    """
    existing = WebhookSigningSecret.query.filter_by(
        provider_org_guid=provider_org_guid,
        status='active',
    ).first()
    if existing:
        return {
            'code': 'already_exists',
            'message': 'Active signing secret already exists. Use rotate.',
            'existing_guid': existing.guid,
        }, 409

    plaintext = _generate_secret()
    row = WebhookSigningSecret(
        provider_org_guid=provider_org_guid,
        secret_encrypted=_encrypt(plaintext),
        status='active',
        created_by_user_guid=created_by_user_guid or 'system',
    )
    db.session.add(row)
    db.session.commit()

    log_event(
        user_guid=created_by_user_guid,
        action='webhook_secret.issued',
        resource_type='WebhookSigningSecret',
        resource_guid=row.guid,
        details={'provider_org_guid': provider_org_guid},
        ip_address=ip_address,
    )

    result = row.to_dict()
    result['secret_plaintext'] = plaintext  # shown ONCE
    return result, 201


def rotate_secret(provider_org_guid, *, created_by_user_guid,
                  ip_address=None):
    """Issue a new active secret; mark previous active as deprecated.

    Returns (result_dict_with_new_plaintext, status_code).
    """
    current = WebhookSigningSecret.query.filter_by(
        provider_org_guid=provider_org_guid,
        status='active',
    ).first()

    plaintext = _generate_secret()
    new_row = WebhookSigningSecret(
        provider_org_guid=provider_org_guid,
        secret_encrypted=_encrypt(plaintext),
        status='active',
        created_by_user_guid=created_by_user_guid or 'system',
    )
    db.session.add(new_row)
    db.session.flush()  # so we have new_row.guid before linking

    if current:
        current.status = 'deprecated'
        current.deprecated_at = datetime.now(timezone.utc)
        current.rotated_to_guid = new_row.guid

    db.session.commit()

    log_event(
        user_guid=created_by_user_guid,
        action='webhook_secret.rotated',
        resource_type='WebhookSigningSecret',
        resource_guid=new_row.guid,
        details={
            'provider_org_guid': provider_org_guid,
            'previous_guid': current.guid if current else None,
        },
        ip_address=ip_address,
    )

    result = new_row.to_dict()
    result['secret_plaintext'] = plaintext  # shown ONCE
    return result, 201


def revoke_secret(provider_org_guid, *, user_guid=None, ip_address=None):
    """Revoke every active and deprecated secret for the org."""
    now = datetime.now(timezone.utc)
    rows = WebhookSigningSecret.query.filter(
        WebhookSigningSecret.provider_org_guid == provider_org_guid,
        WebhookSigningSecret.status.in_(['active', 'deprecated']),
    ).all()
    if not rows:
        return {
            'code': 'not_found',
            'message': 'No active or deprecated secret to revoke.',
        }, 404

    for row in rows:
        row.status = 'revoked'
        row.revoked_at = now
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='webhook_secret.revoked',
        resource_type='WebhookSigningSecret',
        resource_guid=','.join(r.guid for r in rows),
        details={
            'provider_org_guid': provider_org_guid,
            'revoked_count': len(rows),
        },
        ip_address=ip_address,
    )
    return {'revoked_guids': [r.guid for r in rows]}, 200


def get_signing_secret(provider_org_guid):
    """Return the plaintext of the currently-active signing secret,
    or None if the org has none."""
    row = WebhookSigningSecret.query.filter_by(
        provider_org_guid=provider_org_guid,
        status='active',
    ).first()
    if not row:
        return None
    return _decrypt(row.secret_encrypted)


def get_verification_secrets(provider_org_guid):
    """Return plaintexts of every secret that should be accepted on
    inbound verification (active + grace-period deprecated)."""
    rows = WebhookSigningSecret.query.filter_by(
        provider_org_guid=provider_org_guid,
    ).all()
    return [
        _decrypt(r.secret_encrypted)
        for r in rows
        if r.is_valid_for_verification()
    ]
