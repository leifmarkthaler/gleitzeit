import json, uuid, time
from typing import Dict, Any
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from .settings import settings

STREAM = settings.stream_name

async def get_redis() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=False)

async def ensure_group(r: Redis, group: str):
    try:
        await r.xgroup_create(STREAM, group, id="$", mkstream=True)
    except ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

async def emit(r: Redis, type_: str, payload: Dict[str, Any], key: str | None = None):
    evt = {
        "event_id": str(uuid.uuid4()),
        "type": type_,
        "occurred_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "key": key or "",
        "payload": json.dumps(payload),
    }
    msg_id = await r.xadd(STREAM, evt)
    return msg_id, evt

async def set_idempotent(r: Redis, event_id: str) -> bool:
    k = f"{settings.idem_prefix}:{event_id}"
    ok = await r.set(k, 1, nx=True, ex=settings.idem_ttl_seconds)
    return bool(ok)
