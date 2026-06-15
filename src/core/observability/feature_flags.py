"""
Feature Flag system — lightweight Redis-backed feature flags.

Usage:
    from src.core.observability.feature_flags import feature_flags

    if await feature_flags.is_enabled("new_coding_engine"):
        ...
    
    # With user targeting (A/B testing)
    variant = await feature_flags.get_variant("ai_model_v2", user_id="abc123")
    if variant == "treatment":
        ...
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import structlog

logger = structlog.get_logger()

# Built-in default flags — override via Redis or environment
DEFAULT_FLAGS: dict[str, dict] = {
    # AI features
    "ai_chat_enabled": {"enabled": True, "rollout_pct": 100},
    "ai_batch_coding": {"enabled": True, "rollout_pct": 100},
    "ai_appeal_generation": {"enabled": True, "rollout_pct": 100},
    "ai_revenue_insights": {"enabled": True, "rollout_pct": 100},
    "ai_streaming_responses": {"enabled": True, "rollout_pct": 100},
    # Canary flags
    "canary_new_claim_engine": {"enabled": False, "rollout_pct": 0},
    "canary_qdrant_rag": {"enabled": False, "rollout_pct": 0},
    # A/B test flags
    "ab_coding_confidence_display": {
        "enabled": True,
        "rollout_pct": 50,
        "variants": ["control", "treatment"],
    },
    # Operational flags
    "maintenance_mode": {"enabled": False, "rollout_pct": 0},
    "read_only_mode": {"enabled": False, "rollout_pct": 0},
    "rate_limit_strict": {"enabled": False, "rollout_pct": 0},
}

_REDIS_PREFIX = "ff:"
_CACHE_TTL = 30  # seconds — local in-process cache


class FeatureFlagService:
    """Redis-backed feature flags with in-process cache and graceful fallback."""

    def __init__(self):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                from src.config import get_settings
                s = get_settings()
                self._redis = aioredis.from_url(s.redis_url, decode_responses=True)
            except Exception:
                pass
        return self._redis

    async def _load_flag(self, flag_name: str) -> dict:
        """Load flag from cache → Redis → default."""
        now = time.monotonic()
        if flag_name in self._cache:
            val, expires = self._cache[flag_name]
            if now < expires:
                return val

        try:
            r = self._get_redis()
            if r:
                raw = await r.get(f"{_REDIS_PREFIX}{flag_name}")
                if raw:
                    val = json.loads(raw)
                    self._cache[flag_name] = (val, now + _CACHE_TTL)
                    return val
        except Exception as e:
            logger.debug("feature_flag_redis_miss", flag=flag_name, error=str(e))

        val = DEFAULT_FLAGS.get(flag_name, {"enabled": False, "rollout_pct": 0})
        self._cache[flag_name] = (val, now + _CACHE_TTL)
        return val

    async def is_enabled(self, flag_name: str, user_id: str | None = None) -> bool:
        """Return True if flag is enabled for this user."""
        flag = await self._load_flag(flag_name)
        if not flag.get("enabled", False):
            return False
        pct = flag.get("rollout_pct", 100)
        if pct >= 100:
            return True
        if pct <= 0:
            return False
        # Deterministic per-user bucket via hash
        key = f"{flag_name}:{user_id or 'anon'}"
        bucket = int(hashlib.md5(key.encode()).hexdigest(), 16) % 100
        return bucket < pct

    async def get_variant(self, flag_name: str, user_id: str) -> str | None:
        """A/B variant assignment — returns variant name or None if disabled."""
        flag = await self._load_flag(flag_name)
        if not flag.get("enabled", False):
            return None
        variants = flag.get("variants", ["control", "treatment"])
        if not variants:
            return None
        key = f"{flag_name}:{user_id}"
        idx = int(hashlib.md5(key.encode()).hexdigest(), 16) % len(variants)
        return variants[idx]

    async def set_flag(self, flag_name: str, config: dict, ttl: int = 0) -> bool:
        """Update a flag in Redis (admin operation)."""
        try:
            r = self._get_redis()
            if r:
                serialized = json.dumps(config)
                if ttl:
                    await r.setex(f"{_REDIS_PREFIX}{flag_name}", ttl, serialized)
                else:
                    await r.set(f"{_REDIS_PREFIX}{flag_name}", serialized)
                # Invalidate local cache
                self._cache.pop(flag_name, None)
                logger.info("feature_flag_updated", flag=flag_name, config=config)
                return True
        except Exception as e:
            logger.error("feature_flag_set_failed", flag=flag_name, error=str(e))
        return False

    async def get_all_flags(self) -> dict[str, dict]:
        """Get all flags (merges defaults with Redis overrides)."""
        flags = dict(DEFAULT_FLAGS)
        try:
            r = self._get_redis()
            if r:
                keys = await r.keys(f"{_REDIS_PREFIX}*")
                for key in keys:
                    flag_name = key[len(_REDIS_PREFIX):]
                    raw = await r.get(key)
                    if raw:
                        flags[flag_name] = json.loads(raw)
        except Exception:
            pass
        return flags


# Singleton
feature_flags = FeatureFlagService()
