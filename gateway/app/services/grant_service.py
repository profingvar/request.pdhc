"""Data Exchange Grant service — issue and validate composite keys."""
import hashlib
import hmac
from datetime import datetime, timezone, timedelta

from flask import current_app

from app import db
from app.models.security_models import DataExchangeGrant
from app.services.audit_service import log_event


def _hmac_secret():
    """Get the HMAC secret for grant token signing."""
    secret = current_app.config.get('HMAC_SECRET')
    if not secret:
        raise RuntimeError(
            'HMAC_SECRET must be explicitly configured. '
            'Do not rely on SECRET_KEY fallback for grant signing.'
        )
    return secret


def _compute_grant_token(sr_guid, patient_guid, org_guid, contract_guid, expires_iso):
    """Compute HMAC-SHA256 grant token from the composite key components."""
    msg = f"{sr_guid}:{patient_guid}:{org_guid}:{contract_guid}:{expires_iso}"
    return hmac.new(
        _hmac_secret().encode('utf-8'),
        msg.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def issue_grant(service_request_guid, patient_guid, provider_org_guid,
                contract_guid, grant_type='bidirectional',
                expires_hours=None, max_uses=None):
    """Issue a DataExchangeGrant for a specific SR + provider.

    Returns:
        tuple: (grant_dict_with_token, status_code)
    """
    if expires_hours is None:
        expires_hours = int(current_app.config.get('PROVIDER_GRANT_EXPIRY_HOURS', 72))

    expires_at = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    expires_iso = expires_at.isoformat()

    grant_token = _compute_grant_token(
        service_request_guid, patient_guid, provider_org_guid,
        contract_guid, expires_iso,
    )

    # Check if an active grant already exists for this combo
    existing = DataExchangeGrant.query.filter_by(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        revoked=False,
    ).first()

    if existing and existing.is_valid():
        result = existing.to_dict()
        result['grant_token'] = existing.grant_token
        return result, 200

    if max_uses is None:
        max_uses_config = current_app.config.get('PROVIDER_GRANT_MAX_USES')
        if max_uses_config:
            max_uses = int(max_uses_config)

    grant = DataExchangeGrant(
        service_request_guid=service_request_guid,
        patient_guid=patient_guid,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        grant_token=grant_token,
        grant_type=grant_type,
        expires_at=expires_at,
        max_uses=max_uses,
    )
    db.session.add(grant)
    db.session.commit()

    log_event(
        action='grant.issued',
        resource_type='DataExchangeGrant',
        resource_guid=grant.guid,
        details={
            'service_request_guid': service_request_guid,
            'patient_guid': patient_guid,
            'provider_org_guid': provider_org_guid,
            'contract_guid': contract_guid,
            'grant_type': grant_type,
            'data_subject_guid': patient_guid,
        },
    )

    result = grant.to_dict()
    result['grant_token'] = grant_token
    return result, 201


def validate_grant_detailed(service_request_guid, patient_guid, provider_org_guid,
                            contract_guid, grant_token):
    """Validate a composite key (4 GUIDs + grant_token) with reason detail.

    Per the provider integration guide (Phase G #4-5), callers need to
    distinguish "expired" from other invalid-grant cases so the response
    code can be GRANT_EXPIRED vs GRANT_TOKEN_INVALID.

    Returns:
        tuple(grant_or_None, reason_str). reason ∈ {
          'valid', 'not_found', 'revoked', 'expired',
          'patient_mismatch', 'invalid_token',
        }
    """
    filters = dict(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
    )
    if contract_guid:
        filters['contract_guid'] = contract_guid

    def _expired(g):
        if not g.expires_at:
            return False
        exp = g.expires_at if g.expires_at.tzinfo else g.expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

    # An SR accumulates several grant rows over its life — every
    # re-dispatch issues a FRESH grant. Match the SPECIFIC token the
    # caller presented (newest first) rather than an arbitrary .first():
    # the old code grabbed the oldest row, which after a re-dispatch is
    # the already-expired one, and returned 'expired' even though a fresh
    # valid grant existed for the same SR.
    grants = (DataExchangeGrant.query.filter_by(**filters)
              .order_by(DataExchangeGrant.created_at.desc()).all())
    if not grants:
        return None, 'not_found'

    grant = next(
        (g for g in grants if hmac.compare_digest(g.grant_token, grant_token)),
        None,
    )
    if grant is None:
        # The presented token matches no grant row for this SR. Report the
        # most informative reason from the newest row.
        newest = grants[0]
        if newest.revoked:
            return None, 'revoked'
        if _expired(newest):
            return None, 'expired'
        return None, 'invalid_token'

    if grant.revoked:
        return None, 'revoked'
    if _expired(grant):
        return None, 'expired'
    if not grant.is_valid():
        return None, 'invalid_token'
    if grant.patient_guid != patient_guid:
        return None, 'patient_mismatch'

    return grant, 'valid'


def validate_grant(service_request_guid, patient_guid, provider_org_guid,
                   contract_guid, grant_token):
    """Backward-compatible wrapper around validate_grant_detailed().

    Returns:
        DataExchangeGrant or None
    """
    grant, _reason = validate_grant_detailed(
        service_request_guid, patient_guid, provider_org_guid,
        contract_guid, grant_token,
    )
    return grant


def use_grant(grant, user_guid=None, action='grant.used', ip_address=None):
    """Record a grant use and audit it."""
    grant.record_use()
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action=action,
        resource_type='DataExchangeGrant',
        resource_guid=grant.guid,
        details={
            'service_request_guid': grant.service_request_guid,
            'patient_guid': grant.patient_guid,
            'provider_org_guid': grant.provider_org_guid,
            'data_subject_guid': grant.patient_guid,
        },
        ip_address=ip_address,
    )


def revoke_grant(grant_guid):
    """Revoke a specific grant."""
    grant = DataExchangeGrant.query.filter_by(guid=grant_guid).first()
    if grant:
        grant.revoked = True
        db.session.commit()
    return grant
