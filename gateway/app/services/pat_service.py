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

    Considers active and grace-period 'deprecated' PATs valid; rejects
    revoked or fully-expired ones. is_valid() applies the three-state
    semantics (ticket #136).

    Returns:
        ProviderAccessToken or None
    """
    # Filter out hard-revoked rows up front so we don't bcrypt-compare
    # against tokens that can never authenticate. Both the legacy
    # `revoked` boolean and the new `status` column are checked.
    pats = ProviderAccessToken.query.filter(
        ProviderAccessToken.revoked.is_(False),
        ProviderAccessToken.status != 'revoked',
    ).all()
    for pat in pats:
        if pat.verify_token(raw_token):
            if pat.is_valid():
                return pat
            return None  # found but expired/grace-expired/revoked
    return None


def revoke_pat(pat_guid, user_guid=None, ip_address=None):
    """Revoke a Provider Access Token.

    Sets both the legacy `revoked` bool and `status='revoked'` so old
    and new consumers reject it.

    Returns:
        tuple: (result_dict, status_code)
    """
    pat = ProviderAccessToken.query.filter_by(guid=pat_guid).first()
    if not pat:
        return {'code': 'not_found', 'message': 'PAT not found'}, 404

    if pat.revoked or pat.status == 'revoked':
        return {'code': 'already_revoked', 'message': 'PAT already revoked'}, 400

    pat.revoked = True
    pat.revoked_at = datetime.now(timezone.utc)
    pat.status = 'revoked'
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


def rotate_pat(provider_org_guid, contract_guid, *,
               created_by_user_guid=None, ip_address=None,
               expires_days=None):
    """Issue a new active PAT; mark any existing active/deprecated
    PATs for the same org+contract as 'deprecated' so the provider
    has a grace window (PAT_DEPRECATED_GRACE_DAYS) to swap tokens.

    Returns (result_with_raw_token, status_code).
    """
    # Find the current active PAT (most recent if multiple).
    current = (ProviderAccessToken.query
               .filter_by(provider_org_guid=provider_org_guid,
                          contract_guid=contract_guid,
                          status='active')
               .order_by(ProviderAccessToken.created_at.desc())
               .first())

    # Carry forward delivery_mode + push config so the rotation doesn't
    # silently switch a push-mode provider to poll.
    delivery_mode = current.delivery_mode if current else 'poll'
    push_endpoint_url = current.push_endpoint_url if current else None
    push_auth_key = current.push_auth_key_encrypted if current else None
    scopes = current.scopes if current else 'read'

    result, status = issue_pat(
        provider_org_guid=provider_org_guid,
        contract_guid=contract_guid,
        scopes=scopes,
        delivery_mode=delivery_mode,
        push_endpoint_url=push_endpoint_url,
        push_auth_key=push_auth_key,
        expires_days=expires_days,
        created_by_user_guid=created_by_user_guid,
        ip_address=ip_address,
    )
    if status != 201:
        return result, status

    if current:
        now = datetime.now(timezone.utc)
        current.status = 'deprecated'
        current.deprecated_at = now
        current.rotated_to_guid = result['guid']
        db.session.commit()

        log_event(
            user_guid=created_by_user_guid,
            action='pat.rotated',
            resource_type='ProviderAccessToken',
            resource_guid=result['guid'],
            details={
                'provider_org_guid': provider_org_guid,
                'contract_guid': contract_guid,
                'previous_guid': current.guid,
            },
            ip_address=ip_address,
        )

    return result, 201


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
