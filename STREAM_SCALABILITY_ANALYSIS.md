# Stream Processor Tasks - Scalability Analysis

## Scalability Concerns

### Problem: One Task Per Stream
If we create one asyncio task per event stream type, we could have issues:

1. **Task Proliferation**:
   - 50 event types = 50 asyncio tasks
   - 100 event types = 100 asyncio tasks
   - Each blocking on XREADGROUP

2. **Resource Usage**:
   - Each task holds a Redis connection
   - Memory overhead per task
   - Context switching overhead

3. **Connection Pool Limits**:
   - Redis connection pools have limits
   - Each XREADGROUP holds a connection while blocking

## Better Solution: Multiplexed Stream Consumer

### Single Consumer, Multiple Streams

```python
class MultiplexedStreamConsumer:
    """
    Single consumer that monitors ALL event streams efficiently.
    Uses Redis XREADGROUP with multiple streams in one call.
    """

    async def consume_all_streams(self):
        # Monitor ALL streams with single XREADGROUP
        streams = {
            'gleitzeit:events:stream:workflow:submitted': '>',
            'gleitzeit:events:stream:task:completed': '>',
            'gleitzeit:events:stream:task:failed': '>',
            # ... 50+ more streams
        }

        # Single blocking call monitors ALL streams
        messages = await redis.xreadgroup(
            group='gleitzeit-processor',
            consumer='consumer-1',
            streams=streams,
            block=0  # Block until ANY stream has data
        )
```

### Scalability Benefits

1. **Single Redis Connection**: One XREADGROUP call monitors all streams
2. **Efficient Blocking**: Redis wakes up when ANY stream gets data
3. **No Task Proliferation**: One task handles all streams
4. **Consumer Groups**: Built-in horizontal scaling

## Horizontal Scaling Pattern

### Multiple Instances, Shared Work

```
Instance 1                Instance 2               Instance 3
─────────                ─────────               ─────────
Consumer Group           Consumer Group          Consumer Group
"processors"             "processors"            "processors"
Consumer: "c1"           Consumer: "c2"          Consumer: "c3"
     │                        │                       │
     └────────────┬───────────┴───────────┬──────────┘
                  │                       │
            Redis Streams            Redis Streams
            (Shared Work)            (Auto-distributed)
```

### How Redis Distributes Work

1. **Consumer Groups**: Each message delivered to ONE consumer in group
2. **Automatic Distribution**: Redis handles work distribution
3. **No Coordination Needed**: Consumers are independent
4. **Fault Tolerance**: Dead consumers' messages can be claimed

## Recommended Scalable Architecture

### 1. Stream Event Router (Single Component)

```python
class StreamEventRouter:
    """
    Scalable stream event router using Redis consumer groups.
    """

    def __init__(self):
        self.consumer_group = f"gleitzeit-router-{socket.gethostname()}"
        self.consumer_id = f"consumer-{uuid.uuid4().hex[:8]}"

    async def start(self):
        # Register all event streams
        self.streams = await self._discover_event_streams()

        # Create consumer groups
        for stream in self.streams:
            await self._ensure_consumer_group(stream)

        # Start single consumer task
        asyncio.create_task(self._consume_loop())

    async def _consume_loop(self):
        """Single loop monitoring all streams."""
        while True:
            # Build stream dict for XREADGROUP
            stream_dict = {stream: '>' for stream in self.streams}

            # Single call monitors ALL streams
            messages = await redis.xreadgroup(
                self.consumer_group,
                self.consumer_id,
                stream_dict,
                count=100,  # Process up to 100 messages per batch
                block=1000  # Block for 1 second max
            )

            # Process messages
            for stream, stream_messages in messages:
                for msg_id, data in stream_messages:
                    await self._route_event(stream, msg_id, data)
```

### 2. Dynamic Stream Discovery

```python
async def _discover_event_streams(self):
    """Discover all event streams dynamically."""
    # Get all keys matching event stream pattern
    streams = await redis.keys('gleitzeit:events:stream:*')

    # Filter out internal streams
    return [s for s in streams if not s.endswith(':internal')]
```

### 3. Sharded Processing (For Extreme Scale)

```python
class ShardedStreamProcessor:
    """
    Shard streams across multiple processors for extreme scale.
    """

    def __init__(self, shard_id: int, total_shards: int):
        self.shard_id = shard_id
        self.total_shards = total_shards

    async def get_my_streams(self):
        """Get streams assigned to this shard."""
        all_streams = await self._discover_event_streams()

        # Consistent hashing to assign streams to shards
        my_streams = []
        for stream in all_streams:
            stream_hash = hashlib.md5(stream.encode()).hexdigest()
            stream_shard = int(stream_hash, 16) % self.total_shards

            if stream_shard == self.shard_id:
                my_streams.append(stream)

        return my_streams
```

## Performance Characteristics

### Single Multiplexed Consumer
- **Streams**: 100+
- **Latency**: ~1ms per event
- **Throughput**: 10,000+ events/sec
- **Memory**: ~50MB
- **Connections**: 1

### Sharded Processors (4 shards)
- **Streams**: 1000+
- **Latency**: ~1ms per event
- **Throughput**: 40,000+ events/sec
- **Memory**: ~200MB total
- **Connections**: 4

## Comparison Table

| Approach | Streams | Tasks | Connections | Throughput | Complexity |
|----------|---------|-------|-------------|------------|------------|
| Task per Stream | 100 | 100 | 100 | Medium | High |
| Multiplexed Consumer | 100 | 1 | 1 | High | Low |
| Sharded (4 shards) | 1000 | 4 | 4 | Very High | Medium |
| Consumer Group (4 instances) | 100 | 4 | 4 | Very High | Low |

## Recommended Implementation

### For Most Use Cases (< 1000 event types)
Use **Single Multiplexed Consumer** with consumer groups:
- Simple to implement
- Handles 100s of event types easily
- Scales horizontally via consumer groups
- Single connection, minimal resources

### For Extreme Scale (> 1000 event types)
Use **Sharded Processors**:
- Divide streams across shards
- Each shard handles subset of streams
- Still uses multiplexing within shard
- Predictable resource usage

## Implementation Priority

1. **Start with Multiplexed Consumer** - Simplest, handles most cases
2. **Add Consumer Groups** - For horizontal scaling
3. **Consider Sharding** - Only if you have 1000+ event types

## Conclusion

The **Multiplexed Stream Consumer** approach is highly scalable:
- Single XREADGROUP call monitors unlimited streams
- Consumer groups provide horizontal scaling
- No task proliferation
- Efficient resource usage
- Redis handles the heavy lifting

This is the approach Redis Streams was designed for!