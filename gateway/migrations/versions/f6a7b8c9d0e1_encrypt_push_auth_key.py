"""Encrypt ProviderAccessToken.push_auth_key at rest (ticket #151)

Re-encrypts any existing PLAINTEXT push_auth_key_encrypted values with the
shared Fernet key (WEBHOOK_SECRETS_KEY) via app.services.secret_crypto.

Idempotent: a row already stored as a valid Fernet token under the current
key is skipped (looks_encrypted), so re-running is safe. Requires
WEBHOOK_SECRETS_KEY in the environment when it runs — it fails loudly rather
than leaving secrets in plaintext.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-25 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

from app.services import secret_crypto


revision = 'f6a7b8c9d0e1'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None

_SEL = sa.text(
    "SELECT id, push_auth_key_encrypted FROM provider_access_tokens "
    "WHERE push_auth_key_encrypted IS NOT NULL"
)
_UPD = sa.text(
    "UPDATE provider_access_tokens SET push_auth_key_encrypted = :v WHERE id = :i"
)


def upgrade():
    """Plaintext -> Fernet ciphertext for every existing row."""
    conn = op.get_bind()
    for row in conn.execute(_SEL).mappings():
        val = row['push_auth_key_encrypted']
        if secret_crypto.looks_encrypted(val):
            continue  # already ciphertext under the current key
        conn.execute(_UPD, {'v': secret_crypto.encrypt(val), 'i': row['id']})


def downgrade():
    """Reverse: Fernet ciphertext -> plaintext (best-effort, key required)."""
    conn = op.get_bind()
    for row in conn.execute(_SEL).mappings():
        val = row['push_auth_key_encrypted']
        if not secret_crypto.looks_encrypted(val):
            continue  # already plaintext
        conn.execute(_UPD, {'v': secret_crypto.decrypt(val), 'i': row['id']})
