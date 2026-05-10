"""
PHI field encryption using AES-256-GCM.

Provides:
- PHIEncryptor: encrypt/decrypt strings with AES-256-GCM
- EncryptedString: SQLAlchemy TypeDecorator for transparent column-level encryption
- Key rotation support with old_key fallback
"""

import hashlib
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import LargeBinary, TypeDecorator
import structlog

from src.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# AES-256-GCM constants
NONCE_SIZE = 12  # 96-bit nonce recommended for GCM
KEY_SIZE = 32    # 256-bit key


def _derive_key(raw_key: str) -> bytes:
    """Derive a 32-byte encryption key from a raw string using SHA-256."""
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


class PHIEncryptor:
    """
    Encrypts and decrypts PHI strings using AES-256-GCM.

    Ciphertext format: nonce (12 bytes) + encrypted data + GCM tag (16 bytes).
    Supports key rotation: decrypt tries old_key if the current key fails.
    """

    def __init__(self, key: str | None = None, old_key: str | None = None):
        self._key = _derive_key(key or settings.phi_encryption_key)
        self._aesgcm = AESGCM(self._key)
        self._old_aesgcm: AESGCM | None = None
        if old_key:
            self._old_aesgcm = AESGCM(_derive_key(old_key))

    def encrypt(self, plaintext: str) -> bytes:
        """Encrypt a string. Returns nonce+ciphertext as bytes."""
        if not plaintext:
            return b""
        nonce = os.urandom(NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ciphertext

    def decrypt(self, data: bytes) -> str:
        """Decrypt bytes back to a string. Tries old key on failure for rotation."""
        if not data:
            return ""
        nonce = data[:NONCE_SIZE]
        ciphertext = data[NONCE_SIZE:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
        except Exception:
            if self._old_aesgcm:
                try:
                    return self._old_aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
                except Exception:
                    raise ValueError("Decryption failed with both current and old keys")
            raise

    def rotate_key(self, new_key: str) -> None:
        """Rotate the encryption key. Current key becomes old_key for decryption fallback."""
        self._old_aesgcm = self._aesgcm
        self._key = _derive_key(new_key)
        self._aesgcm = AESGCM(self._key)
        logger.info("phi_encryption_key_rotated")


# Module-level singleton
_phi_encryptor: PHIEncryptor | None = None


def get_encryptor() -> PHIEncryptor:
    """Get or create the module-level PHIEncryptor singleton."""
    global _phi_encryptor
    if _phi_encryptor is None:
        _phi_encryptor = PHIEncryptor()
    return _phi_encryptor


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy TypeDecorator that transparently encrypts on write
    and decrypts on read. Stores as BYTEA (LargeBinary) in PostgreSQL.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> bytes | None:
        if value is None:
            return None
        encryptor = get_encryptor()
        return encryptor.encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        encryptor = get_encryptor()
        return encryptor.decrypt(bytes(value))