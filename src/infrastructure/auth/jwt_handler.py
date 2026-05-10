"""
JWT token creation and validation.

Uses HS256 with configurable expiry. All tokens include a jti claim
for blacklist tracking on logout.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from jose import jwt
import structlog

from src.config import get_settings
from src.infrastructure.auth.schemas import TokenData

logger = structlog.get_logger()
settings = get_settings()


class AuthenticationError(Exception):
    """Raised when token validation fails."""
    pass


def create_access_token(data: TokenData) -> str:
    """Create a short-lived access token (default 15 minutes)."""
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(data.user_id),
        "email": data.email,
        "user_type": data.user_type,
        "practice_id": str(data.practice_id) if data.practice_id else None,
        "internal_role": data.internal_role,
        "provider_role": data.provider_role,
        "assigned_practice_ids": [str(pid) for pid in data.assigned_practice_ids],
        "jti": str(data.jti or uuid4()),
        "iat": now,
        "exp": now + expires_delta,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(data: TokenData) -> str:
    """Create a long-lived refresh token (default 7 days)."""
    now = datetime.now(timezone.utc)
    expires_delta = timedelta(days=settings.jwt_refresh_token_expire_days)
    payload = {
        "sub": str(data.user_id),
        "email": data.email,
        "user_type": data.user_type,
        "jti": str(data.jti or uuid4()),
        "iat": now,
        "exp": now + expires_delta,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT token.

    Raises AuthenticationError if the token is invalid, expired, or malformed.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {e}")


def get_token_expires_in(token_type: str = "access") -> int:
    """Return expiry duration in seconds for the given token type."""
    if token_type == "refresh":
        return settings.jwt_refresh_token_expire_days * 86400
    return settings.jwt_access_token_expire_minutes * 60