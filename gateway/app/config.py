import os
from datetime import timedelta


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'postgresql://request_admin:request_dev_2026!@localhost:9061/request_pdhc'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change-me')

    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'change-me')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)

    FLASK_ENV = os.environ.get('FLASK_ENV', 'development')
    DEBUG = FLASK_ENV == 'development'

    # When True, all auth checks are bypassed (local dev/debug mode).
    AUTH_DISABLED = os.environ.get('AUTH_DISABLED', 'true').lower() in ('true', '1', 'yes')

    # Upstream service URLs
    IPS_BASE_URL = os.environ.get('IPS_BASE_URL', 'https://ips.pdhc.se')
    IPS_API_KEY = os.environ.get('IPS_API_KEY', '')
    PLAN_BASE_URL = os.environ.get('PLAN_BASE_URL', 'https://plan.pdhc.se')
    PLAN_API_KEY = os.environ.get('PLAN_API_KEY', '')
    SSO_BASE_URL = os.environ.get('SSO_BASE_URL', 'https://sso.pdhc.se')
    SSO_CLIENT_ID = os.environ.get('SSO_CLIENT_ID', '')
    SSO_CLIENT_SECRET = os.environ.get('SSO_CLIENT_SECRET', '')
    SSO_CALLBACK_URL = os.environ.get('SSO_CALLBACK_URL', 'http://localhost:9060/api/v1/auth/callback')
    CONTRACT_BASE_URL = os.environ.get('CONTRACT_BASE_URL', 'https://contract.pdhc.se')

    # Forms delivery to 1177
    FORMS_1177_WEBHOOK_URL = os.environ.get('FORMS_1177_WEBHOOK_URL', 'https://1177.pdhc.se/api/webhook/inbound')
    FORMS_1177_API_KEY = os.environ.get('FORMS_1177_API_KEY', '')
    FORMS_1177_ORG_GUID = os.environ.get('FORMS_1177_ORG_GUID', '14b25a1f-63b4-4369-810b-15388d22947b')

    # Provider delivery
    HMAC_SECRET = os.environ.get('HMAC_SECRET', SECRET_KEY)
    PAT_DEFAULT_EXPIRY_DAYS = int(os.environ.get('PAT_DEFAULT_EXPIRY_DAYS', '365'))
    PROVIDER_GRANT_EXPIRY_HOURS = int(os.environ.get('PROVIDER_GRANT_EXPIRY_HOURS', '72'))
    PROVIDER_GRANT_MAX_USES = os.environ.get('PROVIDER_GRANT_MAX_USES')
    PUSH_TIMEOUT_SECONDS = int(os.environ.get('PUSH_TIMEOUT_SECONDS', '30'))

    # Rate limiting
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', '200 per minute')
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_HEADERS_ENABLED = True

    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
