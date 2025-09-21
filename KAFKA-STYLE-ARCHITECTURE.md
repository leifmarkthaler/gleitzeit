# Kafka-Style Architecture for Gleitzeit

## Overview

Transform Gleitzeit to use a Kafka-style consumer group pattern with Redis Streams, enabling automatic event consumption while maintaining horizontal scalability.

## Core Components

### 1. Stream Worker Service

```python
# src/gleitzeit/workers/stream_worker.py
import asyncio
import logging
import signal
from typing import Dict, Any, Optional, List
from datetime import datetime
import uuid

from gleitzeit.persistence.unified_redis import UnifiedRedisAdapter
from gleitzeit.events import StreamlinedEventBus
from gleitzeit.core.events import GleitzeitEvent

logger = logging.getLogger(__name__)


class StreamWorker:
    """
    Kafka-style consumer worker for Redis Streams.

    Features:
    - Automatic consumption (no manual triggering)
    - Consumer group participation
    - At-least-once delivery guarantee
    - Automatic rebalancing
    - Graceful shutdown
    """

    def __init__(
        self,
        redis_client: UnifiedRedisAdapter,
        worker_id: Optional[str] = None,
        consumer_group: str = "gleitzeit-workers",
        batch_size: int = 10,
        poll_timeout_ms: int = 5000,
        max_retries: int = 3
    ):
        self.redis = redis_client
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.consumer_group = consumer_group
        self.batch_size = batch_size
        self.poll_timeout_ms = poll_timeout_ms
        self.max_retries = max_retries

        # Event bus for handler registry
        self.event_bus = StreamlinedEventBus(redis_client)

        # Streams to consume from
        self.streams = [
            "gleitzeit:events:stream:task:*",
            "gleitzeit:events:stream:workflow:*",
            "gleitzeit:events:stream:system:*"
        ]

        # Lifecycle management
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._current_messages: List[tuple] = []

        # Metrics
        self.metrics = {
            "messages_processed": 0,
            "messages_failed": 0,
            "last_poll": None,
            "started_at": None
        }

    async def start(self):
        """Start the worker - begins consuming from streams."""
        if self._running:
            logger.warning(f"Worker {self.worker_id} already running")
            return

        logger.info(f"Starting Kafka-style worker {self.worker_id}")
        self._running = True
        self.metrics["started_at"] = datetime.utcnow()

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

        # Ensure consumer groups exist
        await self._ensure_consumer_groups()

        # Start consumption loop
        try:
            await self._consumption_loop()
        except Exception as e:
            logger.error(f"Worker {self.worker_id} crashed: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Stop the worker gracefully."""
        if not self._running:
            return

        logger.info(f"Stopping worker {self.worker_id}")
        self._running = False

        # Process remaining messages
        if self._current_messages:
            logger.info(f"Processing {len(self._current_messages)} remaining messages")
            await self._process_batch(self._current_messages)

        # Leave consumer group cleanly
        await self._leave_consumer_group()

        logger.info(f"Worker {self.worker_id} stopped. Stats: {self.metrics}")

    async def _consumption_loop(self):
        """
        Main consumption loop - Kafka-style.

        This is the key difference from the current architecture:
        - Runs continuously
        - Blocks waiting for messages
        - Automatically distributes work via consumer groups
        """
        logger.info(f"Worker {self.worker_id} entering consumption loop")

        while self._running:
            try:
                # Build stream dict for XREADGROUP
                stream_dict = {stream: ">" for stream in self.streams}

                # BLOCKING READ - This is the Kafka-style pattern
                # Blocks for poll_timeout_ms, returns immediately if messages available
                messages = await self.redis.xreadgroup(
                    group=self.consumer_group,
                    consumer=self.worker_id,
                    streams=stream_dict,
                    count=self.batch_size,
                    block=self.poll_timeout_ms
                )

                self.metrics["last_poll"] = datetime.utcnow()

                if messages:
                    # Process the batch
                    self._current_messages = messages
                    await self._process_batch(messages)
                    self._current_messages = []

                # Check for shutdown
                if self._shutdown_event.is_set():
                    logger.info(f"Worker {self.worker_id} received shutdown signal")
                    break

            except asyncio.CancelledError:
                logger.info(f"Worker {self.worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Error in consumption loop: {e}")
                await asyncio.sleep(1)  # Brief pause before retry

    async def _process_batch(self, messages: List[tuple]):
        """
        Process a batch of messages.

        Args:
            messages: List of (stream_key, message_id, data) tuples
        """
        successfully_processed = []

        for stream_key, message_id, data in messages:
            try:
                # Decode and process event
                event = self._decode_event(data)
                await self._process_event(event)

                successfully_processed.append((stream_key, message_id))
                self.metrics["messages_processed"] += 1

            except Exception as e:
                logger.error(f"Failed to process message {message_id}: {e}")
                self.metrics["messages_failed"] += 1

                # Optionally: Add to DLQ or retry logic here
                await self._handle_failed_message(stream_key, message_id, data, e)

        # ACK successfully processed messages (Kafka-style commit)
        if successfully_processed:
            await self._acknowledge_messages(successfully_processed)

    async def _acknowledge_messages(self, messages: List[tuple]):
        """
        Acknowledge processed messages (equivalent to Kafka commit).

        Args:
            messages: List of (stream_key, message_id) tuples
        """
        for stream_key, message_id in messages:
            try:
                await self.redis.xack(stream_key, self.consumer_group, message_id)
                logger.debug(f"ACK'd message {message_id} from {stream_key}")
            except Exception as e:
                logger.error(f"Failed to ACK message {message_id}: {e}")

    async def _ensure_consumer_groups(self):
        """Ensure consumer groups exist for all streams."""
        for stream_pattern in self.streams:
            # Get actual stream keys
            stream_keys = await self.redis.keys(stream_pattern)

            for stream_key in stream_keys:
                try:
                    # Create consumer group (idempotent operation)
                    await self.redis.xgroup_create(
                        stream_key,
                        self.consumer_group,
                        id="0",  # Start from beginning
                        mkstream=True
                    )
                    logger.debug(f"Ensured consumer group for {stream_key}")
                except Exception as e:
                    if "BUSYGROUP" not in str(e):
                        logger.error(f"Failed to create consumer group: {e}")

    def _decode_event(self, data: Dict) -> GleitzeitEvent:
        """Decode stream data into event object."""
        # Implementation matches StreamlinedEventBus._decode_event
        pass

    async def _process_event(self, event: GleitzeitEvent):
        """Process a single event through registered handlers."""
        # Use the event bus's handler registry
        handlers = self.event_bus._handlers.get(event.event_type.value.lower(), [])

        for handler in handlers:
            if asyncio.iscoroutinefunction(handler):
                await handler(event)
            else:
                handler(event)

    def _handle_shutdown_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Worker {self.worker_id} received signal {signum}")
        self._shutdown_event.set()


class WorkerPool:
    """
    Manages a pool of Kafka-style workers.

    Features:
    - Automatic worker scaling
    - Health monitoring
    - Load balancing via consumer groups
    """

    def __init__(
        self,
        redis_client: UnifiedRedisAdapter,
        num_workers: int = 4,
        consumer_group: str = "gleitzeit-workers"
    ):
        self.redis = redis_client
        self.num_workers = num_workers
        self.consumer_group = consumer_group
        self.workers: List[StreamWorker] = []
        self._running = False

    async def start(self):
        """Start the worker pool."""
        if self._running:
            return

        logger.info(f"Starting worker pool with {self.num_workers} workers")
        self._running = True

        # Create and start workers
        for i in range(self.num_workers):
            worker = StreamWorker(
                redis_client=self.redis,
                worker_id=f"worker-{i}",
                consumer_group=self.consumer_group
            )
            self.workers.append(worker)

            # Start worker in background task
            asyncio.create_task(worker.start())

        logger.info(f"Worker pool started with {len(self.workers)} workers")

    async def stop(self):
        """Stop all workers in the pool."""
        if not self._running:
            return

        logger.info("Stopping worker pool")
        self._running = False

        # Stop all workers
        await asyncio.gather(*[worker.stop() for worker in self.workers])

        logger.info("Worker pool stopped")

    async def scale(self, new_size: int):
        """
        Scale the worker pool up or down.

        Args:
            new_size: New number of workers
        """
        current_size = len(self.workers)

        if new_size > current_size:
            # Scale up
            for i in range(current_size, new_size):
                worker = StreamWorker(
                    redis_client=self.redis,
                    worker_id=f"worker-{i}",
                    consumer_group=self.consumer_group
                )
                self.workers.append(worker)
                asyncio.create_task(worker.start())

            logger.info(f"Scaled up from {current_size} to {new_size} workers")

        elif new_size < current_size:
            # Scale down
            workers_to_stop = self.workers[new_size:]
            self.workers = self.workers[:new_size]

            await asyncio.gather(*[worker.stop() for worker in workers_to_stop])

            logger.info(f"Scaled down from {current_size} to {new_size} workers")
```

### 2. CLI Integration

```python
# src/gleitzeit/cli/worker.py
import click
import asyncio
from gleitzeit.workers.stream_worker import StreamWorker, WorkerPool
from gleitzeit.persistence.factory import PersistenceFactory


@click.command()
@click.option('--workers', '-w', default=1, help='Number of workers to start')
@click.option('--group', '-g', default='gleitzeit-workers', help='Consumer group name')
@click.option('--batch-size', '-b', default=10, help='Batch size per poll')
@click.option('--poll-timeout', '-t', default=5000, help='Poll timeout in milliseconds')
def worker(workers: int, group: str, batch_size: int, poll_timeout: int):
    """
    Start Kafka-style stream workers.

    Examples:
        # Single worker
        gleitzeit worker

        # Worker pool with 4 workers
        gleitzeit worker --workers 4

        # Custom consumer group
        gleitzeit worker --group high-priority-workers
    """
    async def run():
        # Get Redis connection
        persistence = await PersistenceFactory.create()
        redis = persistence.redis

        if workers == 1:
            # Single worker mode
            worker = StreamWorker(
                redis_client=redis,
                consumer_group=group,
                batch_size=batch_size,
                poll_timeout_ms=poll_timeout
            )

            click.echo(f"🚀 Starting single worker in group '{group}'")
            await worker.start()

        else:
            # Worker pool mode
            pool = WorkerPool(
                redis_client=redis,
                num_workers=workers,
                consumer_group=group
            )

            click.echo(f"🚀 Starting {workers} workers in group '{group}'")
            await pool.start()

            # Keep running until interrupted
            try:
                await asyncio.Event().wait()
            except KeyboardInterrupt:
                await pool.stop()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        click.echo("\n👋 Worker shutdown complete")
```

### 3. Kubernetes Deployment (Kafka-style)

```yaml
# k8s/worker-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 3  # Number of worker pods
  selector:
    matchLabels:
      app: gleitzeit-worker
  template:
    metadata:
      labels:
        app: gleitzeit-worker
    spec:
      containers:
      - name: worker
        image: gleitzeit:latest
        command: ["gleitzeit", "worker"]
        args: ["--workers", "2"]  # 2 workers per pod
        env:
        - name: REDIS_HOST
          value: redis-service
        - name: CONSUMER_GROUP
          value: gleitzeit-workers
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
# Horizontal Pod Autoscaler
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gleitzeit-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-workers
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 4. Docker Compose (Development)

```yaml
# docker-compose.kafka-style.yaml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data

  api:
    image: gleitzeit:latest
    command: gleitzeit serve --host 0.0.0.0
    ports:
      - "8000:8000"
    environment:
      - REDIS_HOST=redis
    depends_on:
      - redis

  workers:
    image: gleitzeit:latest
    command: gleitzeit worker --workers 4
    environment:
      - REDIS_HOST=redis
    depends_on:
      - redis
      - api
    deploy:
      replicas: 2  # 2 containers, 4 workers each = 8 total workers

volumes:
  redis-data:
```

### 5. Stream Sharding (Kafka Partitions Equivalent)

```python
# src/gleitzeit/events/sharded_streams.py
class ShardedStreamEmitter:
    """
    Implements Kafka-style partitioning for Redis Streams.

    Distributes events across multiple streams for parallel consumption.
    """

    def __init__(self, redis_client, num_shards: int = 8):
        self.redis = redis_client
        self.num_shards = num_shards

    async def emit(self, event: GleitzeitEvent) -> str:
        """Emit event to a sharded stream."""
        # Determine shard based on key (like Kafka partition key)
        partition_key = event.data.get("workflow_id", event.correlation_id)
        shard = hash(partition_key) % self.num_shards

        # Stream key includes shard number
        stream_key = f"gleitzeit:events:stream:{event.event_type.value}:{shard}"

        # Add to sharded stream
        return await self.redis.xadd(stream_key, event.to_dict())


class ShardedStreamWorker(StreamWorker):
    """Worker that consumes from sharded streams."""

    def __init__(self, *args, shard_id: Optional[int] = None, **kwargs):
        super().__init__(*args, **kwargs)

        if shard_id is not None:
            # Consume only from specific shard (sticky partition)
            self.streams = [
                f"gleitzeit:events:stream:*:{shard_id}"
            ]
        else:
            # Consume from all shards
            self.streams = [
                f"gleitzeit:events:stream:*:*"
            ]
```

### 6. Monitoring & Observability

```python
# src/gleitzeit/workers/monitoring.py
class WorkerMetricsExporter:
    """
    Exports Kafka-style consumer metrics.

    Metrics:
    - Consumer lag (pending messages)
    - Processing rate
    - Error rate
    - Consumer group membership
    """

    async def get_consumer_lag(self) -> Dict[str, int]:
        """Get pending messages per stream (like Kafka consumer lag)."""
        lag = {}

        for stream in self.streams:
            info = await self.redis.xpending_range(
                stream,
                self.consumer_group,
                min="-",
                max="+",
                count=1000
            )
            lag[stream] = len(info)

        return lag

    async def export_metrics(self):
        """Export metrics to Prometheus/Grafana."""
        while True:
            lag = await self.get_consumer_lag()

            # Export to Prometheus
            for stream, count in lag.items():
                consumer_lag_gauge.labels(
                    stream=stream,
                    consumer_group=self.consumer_group
                ).set(count)

            await asyncio.sleep(10)  # Export every 10 seconds
```

## Key Differences from Current Architecture

| Aspect | Current (Stateless) | Kafka-Style |
|--------|-------------------|-------------|
| **Consumption** | Manual trigger required | Automatic, continuous |
| **Workers** | None | Always running |
| **Scaling** | Can't scale consumers | Horizontal scaling via consumer groups |
| **Latency** | High (waits for trigger) | Low (immediate processing) |
| **Delivery** | May miss events | At-least-once guarantee |
| **Complexity** | Simple but non-functional | More complex but production-ready |

## Migration Path

1. **Phase 1**: Add worker command to CLI
2. **Phase 2**: Update documentation to include worker startup
3. **Phase 3**: Add Kubernetes manifests for production
4. **Phase 4**: Add monitoring/metrics
5. **Phase 5**: Implement stream sharding for scale

## Usage Examples

### Development
```bash
# Terminal 1: Start API
gleitzeit serve

# Terminal 2: Start workers
gleitzeit worker --workers 4
```

### Production (Kubernetes)
```bash
# Deploy everything
kubectl apply -f k8s/

# Scale workers
kubectl scale deployment gleitzeit-workers --replicas=10

# Check consumer lag
kubectl exec -it gleitzeit-worker-xyz -- gleitzeit worker status
```

### Docker Compose
```bash
# Start entire system
docker-compose -f docker-compose.kafka-style.yaml up -d

# Scale workers
docker-compose -f docker-compose.kafka-style.yaml up -d --scale workers=5
```

## Benefits

1. **Automatic Processing**: No manual triggers needed
2. **Horizontal Scalability**: Add workers to increase throughput
3. **Fault Tolerance**: Consumer groups ensure no message loss
4. **Load Balancing**: Redis automatically distributes messages
5. **Production Ready**: Battle-tested pattern used by Kafka, Netflix, Uber

This Kafka-style approach maintains the benefits of stateless workers (each worker has no persistent state) while ensuring automatic event consumption through Redis Streams' consumer group mechanism.