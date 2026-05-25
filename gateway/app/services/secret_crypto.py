"""Shared symmetric secret encryption (Fernet), keyed by WEBHOOK_SECRETS_KEY.

Single source of truth for at-rest secret encryption in request.pdhc.
Introduced for #151 (encrypt ProviderAccessToken.push_auth_key) by lifting
the Fernet plumbing that #136 first added in webhook_secret_service.py, so
both the webhook signing-secret and the PAT push_auth_key use the same key
and scheme.

Key: env ``WEBHOOK_SECRETS_KEY`` (32-byte URL-safe base64). Generate with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
The same key must be present wherever secrets are written or read; losing it
makes every encrypted value unrecoverable, so it is stored in the service
.env (which the server backup captures) — never committed to git.
"""
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _fernet():
    """Return a Fernet instance keyed from WEBHOOK_SECRETS_KEY env."""
    key = os.environ.get('WEBHOOK_SECRETS_KEY', '')
    if not key:
        raise RuntimeError(
            'WEBHOOK_SECRETS_KEY env not set — refusing to handle '
            'encrypted secrets without an encryption key. Generate with: '
            'python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(key.encode('utf-8'))


def encrypt(plaintext):
    """Encrypt a unicode string -> Fernet token (unicode). None -> None."""
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode('utf-8')).decode('utf-8')


def decrypt(ciphertext):
    """Decrypt a Fernet token -> unicode string. None -> None."""
    if ciphertext is None:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        logger.error('Failed to decrypt secret — wrong key or not encrypted?')
        raise


def looks_encrypted(value):
    """True if ``value`` is a valid Fernet token under the current key.

    Used by the re-encrypt migration to tell already-encrypted rows from
    legacy plaintext, so re-running it is idempotent.
    """
    if not value:
        return False
    try:
        _fernet().decrypt(value.encode('utf-8'))
        return True
    except Exception:
        return False
