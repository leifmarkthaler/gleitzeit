from pydantic import BaseModel
from dotenv import load_dotenv
import os
load_dotenv()

class Settings(BaseModel):
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    stream_name: str = os.getenv("STREAM_NAME", "events:main")
    group_email: str = os.getenv("GROUP_EMAIL", "svc.email")
    group_ws: str = os.getenv("GROUP_WS", "svc.ws")
    consumer_prefix: str = os.getenv("CONSUMER_PREFIX", "worker")
    idem_prefix: str = os.getenv("IDEMP_PREFIX", "idem")
    idem_ttl_seconds: int = int(os.getenv("IDEMP_TTL_SECONDS", "86400"))
    dlq_stream: str = os.getenv("DLQ_STREAM", "events:dlq")
    timer_zset: str = os.getenv("TIMER_ZSET", "timers:main")
    timer_claim_batch: int = int(os.getenv("TIMER_CLAIM_BATCH", "64"))
    timer_claim_interval_ms: int = int(os.getenv("TIMER_CLAIM_INTERVAL_MS", "1000"))
    timer_min_idle_ms: int = int(os.getenv("TIMER_MIN_IDLE_MS", "60000"))
    max_deliveries: int = int(os.getenv("MAX_DELIVERIES", "10"))

settings = Settings()
