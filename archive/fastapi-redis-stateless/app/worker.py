import asyncio, json, os
from redis.asyncio import Redis
from .settings import settings
from .streams import ensure_group, set_idempotent

STREAM = settings.stream_name
GROUP = settings.group_email
CONSUMER = f"{settings.consumer_prefix}-{os.getpid()}"

async def handle(fields: dict) -> bool:
    data = {k.decode() if isinstance(k, (bytes, bytearray)) else k:
            v.decode() if isinstance(v, (bytes, bytearray)) else v for k, v in fields.items()}
    payload = json.loads(data["payload"]) if isinstance(data.get("payload"), str) else data.get("payload")
    # TODO: implement business logic
    # simulate success
    return True

async def process_loop():
    r = Redis.from_url(settings.redis_url)
    await ensure_group(r, GROUP)
    while True:
        res = await r.xreadgroup(GROUP, CONSUMER, streams={STREAM: ">"}, count=64, block=5000)
        if not res:
            # reclaim idle messages
            pend = await r.xpending_range(STREAM, GROUP, min="-", max="+", count=64)
            for p in pend:
                if p["time_since_delivered"] > settings.timer_min_idle_ms:
                    await r.xclaim(STREAM, GROUP, CONSUMER, min_idle_time=settings.timer_min_idle_ms, message_ids=[p["message_id"]])
            continue
        for _stream, entries in res:
            for msg_id, fields in entries:
                event_id = fields[b"event_id"].decode()
                deliveries = 1
                try:
                    pending = await r.xpending_range(STREAM, GROUP, min=msg_id, max=msg_id, count=1)
                    if pending:
                        deliveries = pending[0]["deliveries"]
                except Exception:
                    pass
                if deliveries > settings.max_deliveries:
                    # send to DLQ and ack
                    await r.xadd(settings.dlq_stream, {**fields, b"original_id": msg_id})
                    await r.xack(STREAM, GROUP, msg_id)
                    continue
                if not await set_idempotent(r, event_id):
                    await r.xack(STREAM, GROUP, msg_id)
                    continue
                try:
                    ok = await handle(fields)
                    if ok:
                        await r.xack(STREAM, GROUP, msg_id)
                except Exception:
                    # leave unacked for retry
                    pass

if __name__ == "__main__":
    asyncio.run(process_loop())
