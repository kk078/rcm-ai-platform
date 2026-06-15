"""
Authentication service — handles login, MFA, account lockout, and token lifecycle.

All password operations use bcrypt (work factor 12).
MFA uses TOTP (RFC 6238) via pyotp.
Account lockout: 5 failed attempts → 30-minute lock.
MFA challenges backed by Redis DB 3 with 5-minute TTL.
Backup codes: 10 single-use codes, hashed with bcrypt rounds=10.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import bcrypt
import pyotp
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.infrastructure.auth.encryption import get_encryptor
from src.infrastructure.auth.jwt_handler import (
    AuthenticationError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expires_in,
)
from src.infrastructure.auth.schemas import (
    LoginResponse,
    MFAChallengeResponse,
    MFASetupResponse,
    MFAVerifyResponse,
    RefreshResponse,
    TokenData,
)
from src.infrastructure.auth.token_blacklist import token_blacklist

logger = structlog.get_logger()
settings = get_settings()

# Account lockout constants
MAX_LOGIN_ATTEMPTS = settings.max_login_attempts
LOCKOUT_DURATION = timedelta(minutes=settings.lockout_duration_minutes)
MFA_CHALLENGE_TTL = 300  # 5 minutes in seconds
MFA_CHALLENGE_KEY_PREFIX = "mfa_challenge:"


class AuthServiceError(Exception):
    """Base exception for auth service errors."""
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


class AccountLockedError(AuthServiceError):
    pass


class MFARequiredError(AuthServiceError):
    pass


class InvalidMFAError(AuthServiceError):
    pass


class MFANotEnabledError(AuthServiceError):
    pass


class ChallengeExpiredError(AuthServiceError):
    pass


class AuthService:
    """Handles all authentication operations."""

    def __init__(self) -> None:
        # Redis client for MFA challenges (DB 3), lazily initialized
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        """Return (or create) the Redis connection for MFA challenges."""
        if self._redis is None:
            self._redis = await aioredis.from_url(
                settings.redis_mfa_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    # ── Password hashing ───────────────────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt with work factor 12."""
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against a bcrypt hash."""
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    # ── Account lockout ────────────────────────────────────────────────

    @staticmethod
    def is_account_locked(user: User) -> bool:
        """Check if a user account is currently locked."""
        if user.locked_until is None:
            return False
        locked_until = user.locked_until.replace(tzinfo=None) if user.locked_until.tzinfo else user.locked_until
        if datetime.now(timezone.utc).replace(tzinfo=None) >= locked_until:
            return False
        return True

    @staticmethod
    def record_failed_login(user: User) -> dict:
        """
        Increment failed login count and lock account if threshold reached.
        Returns dict with updated fields (caller must commit).
        """
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + LOCKOUT_DURATION
            logger.warning("account_locked", user_id=str(user.id), failed_count=user.failed_login_count)
        return {"failed_login_count": user.failed_login_count, "locked_until": user.locked_until}

    @staticmethod
    def reset_failed_logins(user: User) -> None:
        """Reset failed login count and clear lockout on successful login."""
        user.failed_login_count = 0
        user.locked_until = None

    # ── MFA ─────────────────────────────────────────────────────────────

    def setup_mfa(self, user: User) -> MFASetupResponse:
        """
        Generate a TOTP secret and QR code URI for MFA setup.
        Generates 10 backup codes, hashes each with bcrypt rounds=10,
        and stores the JSON list of hashes in user.mfa_backup_codes.
        The TOTP secret is not enabled until verify_mfa_setup is called.
        """
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        qr_uri = totp.provisioning_uri(name=user.email, issuer_name=settings.mfa_issuer)

        # Generate 10 plaintext backup codes
        plaintext_codes = [secrets.token_hex(4).upper() for _ in range(10)]

        # Hash each with bcrypt rounds=10 and store as JSON list
        hashed_codes = []
        for code in plaintext_codes:
            hashed = bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")
            hashed_codes.append(hashed)
        user.mfa_backup_codes = json.dumps(hashed_codes)

        # Store secret temporarily (not yet enabled) — encrypt it
        encryptor = get_encryptor()
        user.mfa_secret = encryptor.encrypt(secret)

        return MFASetupResponse(
            secret=secret,
            qr_code_uri=qr_uri,
            backup_codes=plaintext_codes,
        )

    @staticmethod
    def verify_mfa_setup(user: User, code: str) -> bool:
        """
        Verify the first TOTP code during MFA setup to confirm the secret.
        Enables MFA on success.
        """
        encryptor = get_encryptor()
        if not user.mfa_secret:
            return False

        secret = encryptor.decrypt(bytes(user.mfa_secret))
        totp = pyotp.TOTP(secret)

        if totp.verify(code, valid_window=1):
            user.mfa_enabled = True
            logger.info("mfa_enabled", user_id=str(user.id))
            return True
        return False

    @staticmethod
    def verify_totp_code(mfa_secret_encrypted: bytes | str, code: str) -> bool:
        """Verify a TOTP code against an encrypted MFA secret."""
        encryptor = get_encryptor()
        secret = encryptor.decrypt(bytes(mfa_secret_encrypted) if isinstance(mfa_secret_encrypted, (bytes, bytearray)) else mfa_secret_encrypted)
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)

    @staticmethod
    def verify_backup_code(user: User, code: str) -> bool:
        """
        Verify a backup code using bcrypt.checkpw().
        The used code is removed (single-use) by updating user.mfa_backup_codes.
        Returns True if a matching code was found and consumed, False otherwise.
        """
        if not user.mfa_backup_codes:
            return False

        try:
            hashed_codes: list[str] = json.loads(user.mfa_backup_codes)
        except (json.JSONDecodeError, TypeError):
            logger.warning("mfa_backup_codes_parse_error", user_id=str(user.id))
            return False

        code_bytes = code.encode("utf-8")
        for i, hashed in enumerate(hashed_codes):
            try:
                if bcrypt.checkpw(code_bytes, hashed.encode("utf-8")):
                    # Remove used code (single-use)
                    hashed_codes.pop(i)
                    user.mfa_backup_codes = json.dumps(hashed_codes)
                    logger.info("mfa_backup_code_used", user_id=str(user.id), remaining=len(hashed_codes))
                    return True
            except Exception:
                continue

        return False

    # ── MFA challenge flow ──────────────────────────────────────────────

    async def create_mfa_challenge(self, user: User) -> MFAChallengeResponse:
        """
        Create an MFA challenge for a user who has MFA enabled.
        Stores the challenge in Redis DB 3 with a 5-minute TTL.
        """
        challenge_id = uuid4()
        redis = await self._get_redis()

        key = f"{MFA_CHALLENGE_KEY_PREFIX}{challenge_id}"
        payload = json.dumps({"user_id": str(user.id)})
        await redis.set(key, payload, ex=MFA_CHALLENGE_TTL)

        logger.debug("mfa_challenge_created", challenge_id=str(challenge_id), user_id=str(user.id))
        return MFAChallengeResponse(
            mfa_challenge_id=challenge_id,
            message="MFA verification required",
        )

    async def verify_mfa_challenge(self, challenge_id: UUID, code: str, db: AsyncSession) -> MFAVerifyResponse:
        """
        Verify an MFA challenge. Tries TOTP first, then backup codes.
        Returns tokens on success.
        Raises ChallengeExpiredError if the challenge has expired or not found.
        Raises InvalidMFAError if the code is wrong.
        """
        from src.infrastructure.database.models import User

        redis = await self._get_redis()
        key = f"{MFA_CHALLENGE_KEY_PREFIX}{challenge_id}"

        raw = await redis.get(key)
        if not raw:
            raise ChallengeExpiredError("MFA challenge not found or expired")

        try:
            challenge = json.loads(raw)
        except json.JSONDecodeError:
            await redis.delete(key)
            raise ChallengeExpiredError("MFA challenge data corrupted")

        user_id = UUID(challenge["user_id"])

        # Load user
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            await redis.delete(key)
            raise InvalidCredentialsError("User not found")

        # Try TOTP first, then backup codes
        totp_valid = self.verify_totp_code(user.mfa_secret, code)
        backup_valid = False
        if not totp_valid:
            backup_valid = self.verify_backup_code(user, code)

        if not totp_valid and not backup_valid:
            raise InvalidMFAError("Invalid MFA code")

        # Clear challenge from Redis
        await redis.delete(key)

        # Issue tokens
        self.reset_failed_logins(user)
        user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)

        token_data = TokenData(
            user_id=user.id,
            email=user.email,
            user_type=user.user_type,
            practice_id=user.practice_id,
            internal_role=user.internal_role,
            provider_role=user.provider_role,
            assigned_practice_ids=[a.practice_id for a in user.staff_assignments] if user.staff_assignments else [],
        )

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return MFAVerifyResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=get_token_expires_in("access"),
        )

    # ── Login ───────────────────────────────────────────────────────────

    async def authenticate(self, email: str, password: str, db: AsyncSession) -> LoginResponse:
        """
        Authenticate a user by email and password.

        - If MFA is enabled, returns a challenge ID instead of tokens.
        - Checks account lockout before verifying password.
        - Records failed login attempts and locks accounts after threshold.
        """
        from src.infrastructure.database.models import User

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            raise InvalidCredentialsError("Invalid email or password")

        if not user.is_active:
            raise InvalidCredentialsError("Account is deactivated")

        if self.is_account_locked(user):
            raise AccountLockedError(
                f"Account is locked. Try again after {user.locked_until.isoformat()}"
            )

        if not self.verify_password(password, user.password_hash):
            self.record_failed_login(user)
            await db.flush()
            raise InvalidCredentialsError("Invalid email or password")

        if user.mfa_enabled:
            challenge = await self.create_mfa_challenge(user)
            return LoginResponse(
                access_token="",
                refresh_token="",
                token_type="bearer",
                expires_in=0,
                requires_mfa=True,
                mfa_challenge_id=challenge.mfa_challenge_id,
            )

        # Successful login — no MFA
        self.reset_failed_logins(user)
        user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)

        token_data = TokenData(
            user_id=user.id,
            email=user.email,
            user_type=user.user_type,
            practice_id=user.practice_id,
            internal_role=user.internal_role,
            provider_role=user.provider_role,
            assigned_practice_ids=[a.practice_id for a in user.staff_assignments] if user.staff_assignments else [],
        )

        access_token = create_access_token(token_data)
        refresh_token = create_refresh_token(token_data)

        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=get_token_expires_in("access"),
        )

    # ── Token refresh ──────────────────────────────────────────────────

    async def refresh_access_token(self, refresh_token: str) -> RefreshResponse:
        """Validate a refresh token and issue a new access token."""
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type")

        jti = payload.get("jti")
        if jti and await token_blacklist.is_blacklisted(jti):
            raise AuthenticationError("Token has been revoked")

        # Issue new access token with the same claims
        token_data = TokenData(
            user_id=UUID(payload["sub"]),
            email=payload["email"],
            user_type=payload["user_type"],
            practice_id=UUID(payload["practice_id"]) if payload.get("practice_id") else None,
            internal_role=payload.get("internal_role"),
            provider_role=payload.get("provider_role"),
            assigned_practice_ids=[UUID(pid) for pid in payload.get("assigned_practice_ids", [])],
        )

        access_token = create_access_token(token_data)

        return RefreshResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=get_token_expires_in("access"),
        )

    # ── Logout ──────────────────────────────────────────────────────────

    async def logout(self, access_token: str, refresh_token: str | None = None) -> None:
        """Blacklist both access and refresh tokens."""
        access_payload = decode_token(access_token)
        access_jti = access_payload.get("jti")
        access_exp = datetime.fromtimestamp(access_payload["exp"], tz=timezone.utc)
        await token_blacklist.add(str(access_jti), access_exp)

        if refresh_token:
            try:
                refresh_payload = decode_token(refresh_token)
                refresh_jti = refresh_payload.get("jti")
                refresh_exp = datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc)
                await token_blacklist.add(str(refresh_jti), refresh_exp)
            except AuthenticationError:
                pass  # Already expired or invalid — safe to ignore

        logger.info("user_logged_out", access_jti=access_jti)


# Module-level singleton
auth_service = AuthService()
