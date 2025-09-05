# FastAPI + Redis Streams (Stateless Events)

A minimal, production-oriented skeleton that keeps **all coordination in Redis** so FastAPI services remain **stateless**.

## Features
- Durable events via **Redis Streams + Consumer Groups** (acks, retries, reclaim)
- **Idempotency** tokens (SET NX EX)
- **Dead-letter queue** (DLQ) after max deliveries
- **Delayed events** via ZSET + claimer
- **WebSocket** broadcaster for UIs
- Dockerized for local dev / CI

## File tree
```
.
├── docker-compose.yml
├── Dockerfile
├── .env
├── requirements.txt
└── app
    ├── main.py
    ├── streams.py
    ├── worker.py
    ├── timers.py
    └── settings.py
```

## Quick start

### 1) Launch
```bash
docker compose up --build
```
API: http://localhost:8000/docs  
WS:  ws://localhost:8000/ws

### 2) Produce events
```bash
curl -X POST http://localhost:8000/events   -H 'content-type: application/json'   -d '{"type":"user.signed_up","key":"user:42","payload":{"user_id":42}}'
```

### 3) Delay an event by 5 minutes
```bash
curl -X POST http://localhost:8000/events/delay   -H 'content-type: application/json'   -d '{"type":"email.reminder","key":"user:42","payload":{"user_id":42},"delay_seconds":300}'
```

### 4) Subscribe via WebSocket
Open a browser console:
```js
const ws = new WebSocket('ws://localhost:8000/ws');
ws.onmessage = e => console.log('event:', JSON.parse(e.data));
```

## Notes
- Workers are **stateless**; delivery, retries, and idempotency live in Redis.
- Tune `MAX_DELIVERIES` and `TIMER_MIN_IDLE_MS` per your SLOs.
- For per-entity ordering, shard streams by hash(key) and run one consumer per shard.
