"""Configuration management for Gleitzeit."""

import os
import socket
from typing import Dict, Any, Optional


class Config:
    """Configuration container."""
    
    def __init__(self):
        # Generate instance-specific consumer group
        instance_id = os.getenv("GLEITZEIT_INSTANCE_ID", f"{socket.gethostname()}-{os.getpid()}")
        default_consumer_group = f"gleitzeit-{instance_id}"

        self.settings = {
            "max_retries": int(os.getenv("GLEITZEIT_MAX_RETRIES", "3")),
            "retry_base_delay": int(os.getenv("GLEITZEIT_RETRY_BASE_DELAY", "10")),
            "retry_max_delay": int(os.getenv("GLEITZEIT_RETRY_MAX_DELAY", "300")),
            "hostname": os.getenv("HOSTNAME", "localhost"),
            "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379"),
            "worker_batch_size": int(os.getenv("GLEITZEIT_WORKER_BATCH_SIZE", "5")),
            "worker_idle_timeout_ms": int(os.getenv("GLEITZEIT_WORKER_IDLE_TIMEOUT", "60000")),
            "dlq_max_size": int(os.getenv("GLEITZEIT_DLQ_MAX_SIZE", "10000")),
            # Event Transport Configuration - Instance-specific consumer group
            "stream_consumer_group": os.getenv("GLEITZEIT_STREAM_CONSUMER_GROUP", default_consumer_group),
            "instance_id": instance_id,
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.settings.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set configuration value."""
        self.settings[key] = value


# Global config instance
_config = Config()


def get_config() -> Config:
    """Get global config instance."""
    return _config