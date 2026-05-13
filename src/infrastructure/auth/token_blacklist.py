"""
Token blacklist for logout and revocation.

Uses an in-memory dict for development. In production, Redis is preferred
for persistence across restarts and multi-process sharing.
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog

from src.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_SENTINEL = object()  # Marker for "we tried Redis and it's not available"


class TokenBlacklist:
    """
    Tracks revoked JWT tokens by their jti claim.

    In-memory implementation auto-evicts expired entries on lookup.
    For production, swap with Redis-backed implementation.
    """

    def __init__(self) -> None:
        self._revoked: dict[str, datetime] = {}  # jti -> expires_at
        self._redis: object = None  # None = not tried, _SENTINEL = tried and unavailable

    async def _get_redis(self):
        """Lazily connect to Redis if available. Returns None if unavailable."""
        if self._redis is _SENTINEL:
            return None
        if self._redis is not None:
            return self._redis
        if not settings.redis_url:
            self._redis = _SENTINEL
            return None
        try:
            import redis.asyncio as aioredis

            conn = aioredis.from_url(settings.redis_url)
            await conn.ping()
            self._redis = conn
            logger.info("token_blacklist_redis_connected")
            return self._redis
        except Exception:
            logger.warning("token_blacklist_redis_unavailable_falling_back_to_memory")
            self._redis = _SENTINEL
            return None

    async def add(self, token_jti: str, expires_at: datetime) -> None:
        """Add a token's jti to the blacklist."""
        # Normalize to naive UTC for consistent comparison
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        redis = await self._get_redis()
        if redis:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            ttl = max(int((expires_at - now).total_seconds()), 0)
            await redis.setex(f"blacklist:{token_jti}", ttl, "1")
            logger.debug("token_blacklisted_redis", jti=token_jti)
        else:
            self._revoked[token_jti] = expires_at
            logger.debug("token_blacklisted_memory", jti=token_jti)

    async def is_blacklisted(self, token_jti: str) -> bool:
        """Check if a token's jti has been revoked. Auto-evicts expired entries."""
        redis = await self._get_redis()
        if redis:
            return await redis.exists(f"blacklist:{token_jti}") > 0

        # In-memory: evict expired entries on each check
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expired_jtis = [jti for jti, exp in self._revoked.items() if exp < now]
        for jti in expired_jtis:
            del self._revoked[jti]

        return token_jti in self._revoked

    async def add_both(
        self, access_jti: str | UUID, access_expires: datetime,
        refresh_jti: str | UUID, refresh_expires: datetime,
    ) -> None:
        """Convenience method to blacklist both access and refresh tokens."""
        await self.add(str(access_jti), access_expires)
        await self.add(str(refresh_jti), refresh_expires)


# Module-level singleton
token_blacklist = TokenBlacklist()