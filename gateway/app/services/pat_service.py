"""Provider Access Token service — issue, validate, revoke, list."""
import secrets
from datetime import datetime, timezone, timedelta

from flask import current_app

from app import db
from app.models.security_models import ProviderAccessToken
from app.services.audit_service import log_event


def issue_pat(provider_org_guid, contract_guid, scopes='read',
              delivery_mode='poll', push_endpoint_url=None,
              push_auth_key=None, expires_days=None,
              created_by_user_guid=None, ip_address=None):
    """Issue a new Provider Access Token.

    Returns:
        tuple: (result_dict_with_raw_token, status_code)
        The raw token is returned ONCE and never stored.
    """
    if delivery_mode == 'push' and not push_endpoint_url:
        return {'code': 'validation_error',
                'message': 'push_endpoint_url required for push delivery mode'}, 400

    raw_token = secrets.token_urlsafe(48)
    token_hash = ProviderAccessToken.hash_token(raw_token)

    if expires_days is None:
        expires_days = int(current_app.config.get('PAT_DEFAULT_EXPIRY_DAYS', 365))

    pat = ProviderAccessToken(
        token_hash=token_hash,
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        scopes=scopes,
        delivery_mode=delivery_mode,
        push_endpoint_url=push_endpoint_url,
        push_auth_key_encrypted=push_auth_key,  # TODO: encrypt with Fernet
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_days),
        created_by_user_guid=created_by_user_guid or 'system',
    )
    db.session.add(pat)
    db.session.commit()

    log_event(
        user_guid=created_by_user_guid,
        action='pat.issued',
        resource_type='ProviderAccessToken',
        resource_guid=pat.guid,
        details={
            'provider_org_guid': provider_org_guid,
            'contract_guid': contract_guid,
            'delivery_mode': delivery_mode,
            'scopes': scopes,
        },
        ip_address=ip_address,
    )

    result = pat.to_dict()
    result['raw_token'] = raw_token  # returned once only
    return result, 201


def validate_pat(raw_token):
    """Validate a raw token against stored PATs.

    Returns:
        ProviderAccessToken or None
    """
    pats = ProviderAccessToken.query.filter_by(revoked=False).all()
    for pat in pats:
        if pat.verify_token(raw_token):
            if pat.is_valid():
                return pat
            return None  # found but expired/revoked
    return None


def revoke_pat(pat_guid, user_guid=None, ip_address=None):
    """Revoke a Provider Access Token.

    Returns:
        tuple: (result_dict, status_code)
    """
    pat = ProviderAccessToken.query.filter_by(guid=pat_guid).first()
    if not pat:
        return {'code': 'not_found', 'message': 'PAT not found'}, 404

    if pat.revoked:
        return {'code': 'already_revoked', 'message': 'PAT already revoked'}, 400

    pat.revoked = True
    pat.revoked_at = datetime.now(timezone.utc)
    db.session.commit()

    log_event(
        user_guid=user_guid,
        action='pat.revoked',
        resource_type='ProviderAccessToken',
        resource_guid=pat.guid,
        details={'provider_org_guid': pat.provider_org_guid},
        ip_address=ip_address,
    )

    return pat.to_dict(), 200


def list_pats(provider_org_guid=None, include_revoked=False):
    """List Provider Access Tokens, optionally filtered.

    Returns:
        tuple: (result_dict, status_code)
    """
    query = ProviderAccessToken.query
    if provider_org_guid:
        query = query.filter_by(provider_org_guid=provider_org_guid)
    if not include_revoked:
        query = query.filter_by(revoked=False)
    pats = query.order_by(ProviderAccessToken.created_at.desc()).all()
    return {'tokens': [p.to_dict() for p in pats]}, 200
