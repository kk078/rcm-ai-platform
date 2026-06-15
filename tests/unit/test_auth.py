"""Tests for authentication and security: JWT, MFA, encryption, lockout, RBAC."""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from unittest.mock import AsyncMock

# Set test encryption key before importing anything that uses it
os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")
os.environ.setdefault("APP_SECRET_KEY", "test-app-secret")


from src.infrastructure.auth.encryption import PHIEncryptor, EncryptedString, get_encryptor
from src.infrastructure.auth.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expires_in,
    AuthenticationError,
)
from src.infrastructure.auth.schemas import TokenData, LoginRequest, LoginResponse
from src.infrastructure.auth.token_blacklist import TokenBlacklist
from src.infrastructure.auth.service import AuthService


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def token_data():
    """Sample TokenData for testing."""
    return TokenData(
        user_id=uuid4(),
        email="test@aetherahealthcare.com",
        user_type="internal",
        practice_id=uuid4(),
        internal_role="company_admin",
        provider_role=None,
        assigned_practice_ids=[],
    )


@pytest.fixture
def auth_service():
    return AuthService()


# ── Password Hashing Tests ──────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_password(self, auth_service):
        password = "SecureP@ssw0rd123"
        hashed = auth_service.hash_password(password)
        assert hashed != password
        assert hashed.startswith("$2b$")

    def test_verify_password_correct(self, auth_service):
        password = "SecureP@ssw0rd123"
        hashed = auth_service.hash_password(password)
        assert auth_service.verify_password(password, hashed) is True

    def test_verify_password_incorrect(self, auth_service):
        hashed = auth_service.hash_password("correct_password")
        assert auth_service.verify_password("wrong_password", hashed) is False

    def test_hash_uses_bcrypt_work_factor_12(self, auth_service):
        hashed = auth_service.hash_password("test123")
        # bcrypt hashes contain the cost factor: $2b$12$
        assert "$2b$12$" in hashed

    def test_different_hashes_for_same_password(self, auth_service):
        """Each hash should be unique due to salt."""
        h1 = auth_service.hash_password("same_password")
        h2 = auth_service.hash_password("same_password")
        assert h1 != h2


# ── JWT Token Tests ─────────────────────────────────────────────────────


class TestJWTTokens:
    def test_create_access_token(self, token_data):
        token = create_access_token(token_data)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self, token_data):
        token = create_refresh_token(token_data)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_decode_access_token(self, token_data):
        token = create_access_token(token_data)
        payload = decode_token(token)
        assert payload["sub"] == str(token_data.user_id)
        assert payload["email"] == token_data.email
        assert payload["user_type"] == token_data.user_type
        assert payload["type"] == "access"

    def test_decode_refresh_token(self, token_data):
        token = create_refresh_token(token_data)
        payload = decode_token(token)
        assert payload["sub"] == str(token_data.user_id)
        assert payload["type"] == "refresh"

    def test_decode_invalid_token_raises(self):
        with pytest.raises(AuthenticationError):
            decode_token("invalid.token.here")

    def test_decode_expired_token_raises(self, token_data):
        """Create token with already-expired data."""
        token_data.exp = datetime.now(timezone.utc) - timedelta(hours=1)
        # Manually encode an expired token
        import jwt
        from src.config import get_settings
        settings = get_settings()
        payload = {
            "sub": str(token_data.user_id),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            "type": "access",
        }
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        with pytest.raises(AuthenticationError, match="expired"):
            decode_token(token)

    def test_token_contains_jti(self, token_data):
        token = create_access_token(token_data)
        payload = decode_token(token)
        assert "jti" in payload

    def test_get_token_expires_in(self):
        access_seconds = get_token_expires_in("access")
        refresh_seconds = get_token_expires_in("refresh")
        assert access_seconds == 15 * 60  # 15 minutes
        assert refresh_seconds == 7 * 24 * 3600  # 7 days


# ── Token Blacklist Tests ────────────────────────────────────────────────


class TestTokenBlacklist:
    @pytest.mark.asyncio
    async def test_add_and_check(self):
        bl = TokenBlacklist()
        jti = str(uuid4())
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        await bl.add(jti, expires)
        assert await bl.is_blacklisted(jti) is True

    @pytest.mark.asyncio
    async def test_not_blacklisted(self):
        bl = TokenBlacklist()
        assert await bl.is_blacklisted(str(uuid4())) is False

    @pytest.mark.asyncio
    async def test_expired_entry_evicted(self):
        bl = TokenBlacklist()
        jti = str(uuid4())
        expires = datetime.now(timezone.utc) - timedelta(seconds=1)  # Already expired
        await bl.add(jti, expires)
        # Expired entries are evicted on check, so they're no longer "blacklisted"
        assert await bl.is_blacklisted(jti) is False

    @pytest.mark.asyncio
    async def test_add_both_tokens(self):
        bl = TokenBlacklist()
        access_jti = str(uuid4())
        refresh_jti = str(uuid4())
        access_exp = datetime.now(timezone.utc) + timedelta(minutes=15)
        refresh_exp = datetime.now(timezone.utc) + timedelta(days=7)
        await bl.add_both(access_jti, access_exp, refresh_jti, refresh_exp)
        assert await bl.is_blacklisted(access_jti) is True
        assert await bl.is_blacklisted(refresh_jti) is True


# ── PHI Encryption Tests ────────────────────────────────────────────────


class TestPHIEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        encryptor = PHIEncryptor(key="test-encryption-key")
        plaintext = "John Doe"
        ciphertext = encryptor.encrypt(plaintext)
        assert isinstance(ciphertext, bytes)
        assert ciphertext != plaintext.encode("utf-8")
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertexts(self):
        """Each encryption uses a random nonce, so ciphertexts differ."""
        encryptor = PHIEncryptor(key="test-encryption-key")
        ct1 = encryptor.encrypt("same input")
        ct2 = encryptor.encrypt("same input")
        assert ct1 != ct2

    def test_encrypt_empty_string(self):
        encryptor = PHIEncryptor(key="test-encryption-key")
        assert encryptor.encrypt("") == b""

    def test_decrypt_empty_bytes(self):
        encryptor = PHIEncryptor(key="test-encryption-key")
        assert encryptor.decrypt(b"") == ""

    def test_decrypt_invalid_data_raises(self):
        encryptor = PHIEncryptor(key="test-encryption-key")
        with pytest.raises(Exception):
            encryptor.decrypt(b"invalid-ciphertext")

    def test_key_rotation(self):
        old_key = "old-encryption-key"
        new_key = "new-encryption-key"
        encryptor_old = PHIEncryptor(key=old_key)
        ciphertext = encryptor_old.encrypt("Sensitive PHI Data")

        # Rotate: new key with old key fallback
        encryptor_new = PHIEncryptor(key=new_key, old_key=old_key)
        decrypted = encryptor_new.decrypt(ciphertext)
        assert decrypted == "Sensitive PHI Data"

    def test_rotation_fails_without_old_key(self):
        old_key = "old-encryption-key"
        new_key = "new-encryption-key"
        encryptor_old = PHIEncryptor(key=old_key)
        ciphertext = encryptor_old.encrypt("Sensitive PHI Data")

        encryptor_new = PHIEncryptor(key=new_key)  # No old_key fallback
        with pytest.raises(Exception):
            encryptor_new.decrypt(ciphertext)

    def test_rotate_key_method(self):
        encryptor = PHIEncryptor(key="original-key")
        ciphertext = encryptor.encrypt("Data before rotation")

        encryptor.rotate_key("rotated-key")
        # After rotation, old key should still decrypt old data
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == "Data before rotation"

    def test_ssn_encryption(self):
        encryptor = PHIEncryptor(key="test-encryption-key")
        ssn = "123-45-6789"
        ciphertext = encryptor.encrypt(ssn)
        assert encryptor.decrypt(ciphertext) == ssn

    def test_get_encryptor_singleton(self):
        e1 = get_encryptor()
        e2 = get_encryptor()
        assert e1 is e2


# ── EncryptedString TypeDecorator Tests ──────────────────────────────────


class TestEncryptedString:
    def test_process_bind_param_encrypts(self):
        es = EncryptedString()
        result = es.process_bind_param("John Doe", dialect=None)
        assert isinstance(result, bytes)
        assert result != b"John Doe"

    def test_process_result_value_decrypts(self):
        es = EncryptedString()
        encrypted = es.process_bind_param("John Doe", dialect=None)
        decrypted = es.process_result_value(encrypted, dialect=None)
        assert decrypted == "John Doe"

    def test_process_bind_param_none(self):
        es = EncryptedString()
        assert es.process_bind_param(None, dialect=None) is None

    def test_process_result_value_none(self):
        es = EncryptedString()
        assert es.process_result_value(None, dialect=None) is None


# ── Account Lockout Tests ───────────────────────────────────────────────


class TestAccountLockout:
    def test_is_account_locked_not_locked(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=0,
            locked_until=None,
        )
        assert auth_service.is_account_locked(user) is False

    def test_is_account_locked_with_future_lockout(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=5,
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        assert auth_service.is_account_locked(user) is True

    def test_is_account_locked_with_expired_lockout(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=5,
            locked_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        assert auth_service.is_account_locked(user) is False

    def test_record_failed_login_increments(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=0,
            locked_until=None,
        )
        result = auth_service.record_failed_login(user)
        assert result["failed_login_count"] == 1
        assert result["locked_until"] is None

    def test_record_failed_login_locks_at_threshold(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=4,  # One away from threshold
            locked_until=None,
        )
        result = auth_service.record_failed_login(user)
        assert result["failed_login_count"] == 5
        assert result["locked_until"] is not None

    def test_reset_failed_logins(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
            failed_login_count=3,
            locked_until=datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        auth_service.reset_failed_logins(user)
        assert user.failed_login_count == 0
        assert user.locked_until is None


# ── MFA Tests ────────────────────────────────────────────────────────────


class TestMFA:
    def test_setup_mfa_generates_secret(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
        )
        result = auth_service.setup_mfa(user)
        assert result.secret is not None
        assert len(result.secret) > 0
        assert result.qr_code_uri.startswith("otpauth://totp/")
        assert len(result.backup_codes) == 10

    def test_setup_mfa_stores_encrypted_secret(self, auth_service):
        from src.infrastructure.database.models import User
        encryptor = get_encryptor()
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
        )
        auth_service.setup_mfa(user)
        # mfa_secret should be encrypted bytes, not plaintext
        assert user.mfa_secret is not None
        decrypted = encryptor.decrypt(bytes(user.mfa_secret))
        assert len(decrypted) > 0  # Should be a valid base32 secret

    @pytest.mark.asyncio
    async def test_create_mfa_challenge(self, auth_service):
        from src.infrastructure.database.models import User
        user = User(
            id=uuid4(),
            email="test@aetherahealthcare.com",
            password_hash=auth_service.hash_password("pass"),
            first_name="Test",
            last_name="User",
            user_type="internal",
        )
        auth_service._redis = AsyncMock()
        challenge = await auth_service.create_mfa_challenge(user)
        assert challenge.mfa_challenge_id is not None
        assert challenge.message == "MFA verification required"

    def test_verify_totp_code(self, auth_service):
        import pyotp
        encryptor = get_encryptor()
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        code = totp.now()

        encrypted_secret = encryptor.encrypt(secret)
        assert auth_service.verify_totp_code(encrypted_secret, code) is True

    def test_verify_totp_code_invalid(self, auth_service):
        encryptor = get_encryptor()
        secret = "JBSWY3DPEHPK3PXP"
        encrypted_secret = encryptor.encrypt(secret)
        assert auth_service.verify_totp_code(encrypted_secret, "000000") is False


# ── Auth Service Integration Tests ───────────────────────────────────────


class TestAuthService:
    def test_login_response_model(self):
        """Test that LoginResponse has the expected fields."""
        response = LoginResponse(
            access_token="token123",
            refresh_token="refresh456",
            token_type="bearer",
            expires_in=900,
            requires_mfa=False,
        )
        assert response.access_token == "token123"
        assert response.refresh_token == "refresh456"
        assert response.token_type == "bearer"
        assert response.expires_in == 900
        assert response.requires_mfa is False

    def test_login_response_with_mfa(self):
        challenge_id = uuid4()
        response = LoginResponse(
            access_token="",
            refresh_token="",
            token_type="bearer",
            expires_in=0,
            requires_mfa=True,
            mfa_challenge_id=challenge_id,
        )
        assert response.requires_mfa is True
        assert response.mfa_challenge_id == challenge_id

    def test_login_request_validation(self):
        """LoginRequest should validate email format."""
        with pytest.raises(Exception):
            LoginRequest(email="not-an-email", password="pass")


# ── RBAC Middleware Tests ────────────────────────────────────────────────


class TestRBAC:
    def test_require_role_factory(self):
        from src.infrastructure.auth.middleware import require_role
        # Should return a callable
        checker = require_role("company_admin", "billing_manager")
        assert callable(checker)

    def test_require_practice_access_factory(self):
        from src.infrastructure.auth.middleware import require_practice_access
        checker = require_practice_access()
        assert callable(checker)

    def test_admin_roles_constant(self):
        from src.infrastructure.auth.middleware import ADMIN_ROLES
        assert "company_admin" in ADMIN_ROLES
        assert "qa_reviewer" in ADMIN_ROLES