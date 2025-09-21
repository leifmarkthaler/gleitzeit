import json, time, asyncio
from redis.asyncio import Redis
from .settings import settings
from .streams import emit

async def schedule_in(r: Redis, type_: str, payload: dict, delay_seconds: int, key: str | None = None):
    when = time.time() + delay_seconds
    item = json.dumps({"type": type_, "payload": payload, "key": key})
    await r.zadd(settings.timer_zset, {item: when})

TIMER_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local batch = tonumber(ARGV[2])
local items = redis.call('ZRANGEBYSCORE', key, '-inf', now, 'LIMIT', 0, batch)
for i, v in ipairs(items) do
  redis.call('ZREM', key, v)
end
return items
"""

async def run_timer_claimer(r: Redis):
    while True:
        try:
            items = await r.eval(TIMER_LUA, 1, settings.timer_zset, int(time.time()), settings.timer_claim_batch)
            if items:
                for raw in items:
                    # redis-py returns bytes; ensure str
                    s = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    obj = json.loads(s)
                    await emit(r, obj["type"], obj["payload"], obj.get("key"))
            await asyncio.sleep(settings.timer_claim_interval_ms / 1000)
        except Exception:
            # simple backoff on error
            await asyncio.sleep(1)
