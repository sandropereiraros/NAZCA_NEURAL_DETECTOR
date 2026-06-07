import json
import logging
from typing import Any

from eew_api.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_redis = None
_memory_queue: list[dict[str, Any]] = []


async def get_redis():
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis

        kwargs: dict = {"decode_responses": True}
        if settings.redis_ssl:
            kwargs["ssl"] = True
        redis = aioredis.from_url(settings.redis_url, **kwargs)
        await redis.ping()
        _redis = redis
        logger.info("Redis conectado")
        return _redis
    except Exception as exc:
        _redis = None
        logger.warning("Redis no disponible, usando cola en memoria: %s", exc)
        return None


async def enqueue_alert(payload: dict[str, Any]) -> str:
    redis = await get_redis()
    if redis:
        msg_id = await redis.xadd(settings.eew_queue_name, {"data": json.dumps(payload)})
        return str(msg_id)
    _memory_queue.append(payload)
    return f"mem-{len(_memory_queue)}"


async def redis_health() -> str:
    redis = await get_redis()
    if redis:
        try:
            await redis.ping()
            return "connected"
        except Exception as exc:
            global _redis
            _redis = None
            logger.warning("Redis perdió conexión, usando cola en memoria: %s", exc)
    return "fallback_memory"
