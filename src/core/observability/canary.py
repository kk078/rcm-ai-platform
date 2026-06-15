"""
Canary release manager — routes traffic to stable vs canary backends.

Usage:
    from src.core.observability.canary import canary_router

    backend = await canary_router.route("coding_engine", user_id)
    if backend == "canary":
        result = await new_coding_engine.process(...)
    else:
        result = await stable_coding_engine.process(...)

Canary config stored in Redis; falls back to stable on any error.
"""

from __future__ import annotations

import hashlib
import json
import time

import structlog

logger = structlog.get_logger()

_REDIS_PREFIX = "canary:"
_CACHE_TTL = 60  # seconds


class CanaryRouter:
    """
    Deterministic per-user canary routing.

    Each canary has a name and a rollout_pct (0-100).
    Users are assigned stable/canary by hashing user_id against the rollout bucket.
    """

    def __init__(self):
        self._cache: dict[str, tuple[dict, float]] = {}
        self._redis = None
        # Built-in canary definitions
        self._defaults: dict[str, dict] = {
            "coding_engine": {"rollout_pct": 0, "stable": "v1", "canary": "v2"},
            "ai_model": {"rollout_pct": 0, "stable": "ollama", "canary": "anthropic"},
            "claim_scrubber": {"rollout_pct": 0, "stable": "rules", "canary": "ml"},
            "denial_classifier": {"rollout_pct": 0, "stable": "v1", "canary": "v2"},
        }

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                from src.config import get_settings
                self._redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
            except Exception:
                pass
        return self._redis

    async def _load_config(self, canary_name: str) -> dict:
        now = time.monotonic()
        if canary_name in self._cache:
            val, exp = self._cache[canary_name]
            if now < exp:
                return val

        try:
            r = self._get_redis()
            if r:
                raw = await r.get(f"{_REDIS_PREFIX}{canary_name}")
                if raw:
                    val = json.loads(raw)
                    self._cache[canary_name] = (val, now + _CACHE_TTL)
                    return val
        except Exception:
            pass

        val = self._defaults.get(canary_name, {"rollout_pct": 0})
        self._cache[canary_name] = (val, now + _CACHE_TTL)
        return val

    async def route(self, canary_name: str, user_id: str) -> str:
        """
        Returns 'canary' or 'stable' for the given user.
        Always returns 'stable' on errors.
        """
        try:
            config = await self._load_config(canary_name)
            pct = config.get("rollout_pct", 0)
            if pct <= 0:
                return config.get("stable", "stable")
            if pct >= 100:
                return config.get("canary", "canary")
            key = f"{canary_name}:{user_id}"
            bucket = int(hashlib.md5(key.encode()).hexdigest(), 16) % 100
            if bucket < pct:
                logger.debug("canary_routed", canary=canary_name, user=user_id, backend="canary")
                return config.get("canary", "canary")
            return config.get("stable", "stable")
        except Exception as e:
            logger.error("canary_route_error", canary=canary_name, error=str(e))
            return "stable"

    async def set_rollout(self, canary_name: str, pct: int) -> bool:
        """Set rollout percentage (0-100) for a canary."""
        pct = max(0, min(100, pct))
        try:
            r = self._get_redis()
            if r:
                config = await self._load_config(canary_name)
                config["rollout_pct"] = pct
                await r.set(f"{_REDIS_PREFIX}{canary_name}", json.dumps(config))
                self._cache.pop(canary_name, None)
                logger.info("canary_rollout_updated", canary=canary_name, pct=pct)
                return True
        except Exception as e:
            logger.error("canary_set_failed", error=str(e))
        return False

    async def get_all_canaries(self) -> dict[str, dict]:
        configs = {}
        for name in self._defaults:
            configs[name] = await self._load_config(name)
        return configs


# Singleton
canary_router = CanaryRouter()
