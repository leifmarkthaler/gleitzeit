from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from redis.asyncio import Redis
import asyncio
from .settings import settings
from .streams import emit, ensure_group, get_redis
from .timers import schedule_in, run_timer_claimer

app = FastAPI(title="Stateless Events API")

class EventIn(BaseModel):
    type: str
    key: str | None = None
    payload: dict

@app.on_event("startup")
async def startup():
    app.state.redis = await get_redis()
    await ensure_group(app.state.redis, settings.group_ws)
    app.state.ws_clients = set()
    # background: timer claimer
    app.state.timer_task = asyncio.create_task(run_timer_claimer(app.state.redis))
    # background: ws broadcaster
    app.state.ws_task = asyncio.create_task(ws_broadcast_loop(app.state.redis))

@app.on_event("shutdown")
async def shutdown():
    for t in ("timer_task", "ws_task"):
        task = getattr(app.state, t, None)
        if task:
            task.cancel()
    r: Redis = app.state.redis
    await r.aclose()

@app.post("/events")
async def post_event(evt: EventIn):
    msg_id, _ = await emit(app.state.redis, evt.type, evt.payload, evt.key)
    return {"status": "enqueued", "id": msg_id}

class DelayIn(BaseModel):
    type: str
    key: str | None = None
    payload: dict
    delay_seconds: int

@app.post("/events/delay")
async def post_delayed(evt: DelayIn):
    await schedule_in(app.state.redis, evt.type, evt.payload, evt.delay_seconds, evt.key)
    return {"status": "scheduled", "after": evt.delay_seconds}

@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    app.state.ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        app.state.ws_clients.discard(ws)

async def ws_broadcast_loop(r: Redis):
    group = settings.group_ws
    consumer = "ws-broadcaster"
    await ensure_group(r, group)
    while True:
        res = await r.xreadgroup(group, consumer, streams={settings.stream_name: ">"}, count=64, block=5000)
        if not res:
            continue
        for _s, entries in res:
            for msg_id, fields in entries:
                msg = {k.decode(): (v.decode() if isinstance(v, (bytes, bytearray)) else v) for k, v in fields.items()}
                payload = msg.get("payload")
                dead = []
                for client in list(app.state.ws_clients):
                    try:
                        await client.send_json({"id": msg_id, **msg, "payload": payload})
                    except Exception:
                        dead.append(client)
                for d in dead:
                    app.state.ws_clients.discard(d)
                await r.xack(settings.stream_name, group, msg_id)
