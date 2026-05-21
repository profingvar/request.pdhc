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


def validate_grant(service_request_guid, patient_guid, provider_org_guid,
                   contract_guid, grant_token):
    """Validate a composite key (4 GUIDs + grant_token).

    Returns:
        DataExchangeGrant or None
    """
    # contract_guid is optional — gateway's GrantValidationService doesn't
    # pass it (it derives contract_guid from the validated grant response).
    # When the caller does provide it, use it as an extra filter; otherwise
    # rely on patient+org+sr+grant_token uniqueness and cross-check below.
    filters = dict(
        service_request_guid=service_request_guid,
        provider_org_guid=provider_org_guid,
        revoked=False,
    )
    if contract_guid:
        filters['contract_guid'] = contract_guid

    grant = DataExchangeGrant.query.filter_by(**filters).first()

    if not grant:
        return None

    if not grant.is_valid():
        return None

    # Verify the patient_guid matches
    if grant.patient_guid != patient_guid:
        return None

    # Verify the HMAC token
    if not hmac.compare_digest(grant.grant_token, grant_token):
        return None

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
