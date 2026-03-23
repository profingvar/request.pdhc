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
    PLAN_BASE_URL = os.environ.get('PLAN_BASE_URL', 'https://plan.pdhc.se')
    SSO_BASE_URL = os.environ.get('SSO_BASE_URL', 'https://sso.pdhc.se')
    SSO_CLIENT_ID = os.environ.get('SSO_CLIENT_ID', '')
    SSO_CLIENT_SECRET = os.environ.get('SSO_CLIENT_SECRET', '')
    SSO_CALLBACK_URL = os.environ.get('SSO_CALLBACK_URL', 'http://localhost:9060/api/v1/auth/callback')

    # Rate limiting
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', '200 per minute')
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_HEADERS_ENABLED = True

    # Session
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
