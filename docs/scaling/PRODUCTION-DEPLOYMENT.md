# Production Deployment Guide for Scaled Gleitzeit

## Overview

This guide provides step-by-step instructions for deploying Gleitzeit with horizontal scaling in production. The architecture supports scaling both orchestration (schedulers) and execution (providers) independently.

## Architecture Components

```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer                         │
└─────────────┬───────────────────────┬───────────────────┘
              │                       │
    ┌─────────▼─────────┐   ┌────────▼─────────┐
    │   Orchestrator    │   │   Orchestrator    │
    │   (Partition 0)   │   │   (Partition 1)   │
    └─────────┬─────────┘   └────────┬─────────┘
              │                       │
    ┌─────────▼───────────────────────▼─────────┐
    │            Redis (Persistence)             │
    │         - Task Queues                      │
    │         - Event Bus                        │
    │         - Distributed Locks                │
    └─────────┬───────────────────────┬─────────┘
              │                       │
    ┌─────────▼─────────┐   ┌────────▼─────────┐
    │  Provider Cluster │   │  Provider Cluster │
    │   (5 workers)     │   │   (5 workers)     │
    └───────────────────┘   └──────────────────┘
```

## Prerequisites

- Python 3.8+
- Redis 6.0+ (clustered for high availability)
- Docker & Kubernetes (recommended) or systemd services
- Monitoring: Prometheus + Grafana (recommended)

## Configuration

### 1. Environment Variables

Create `.env.production`:

```bash
# Redis Configuration
REDIS_HOST=redis-cluster.internal
REDIS_PORT=6379
REDIS_PASSWORD=your_secure_password
REDIS_DB=0
REDIS_SENTINEL_HOSTS=sentinel1:26379,sentinel2:26379,sentinel3:26379

# Scaling Configuration
ORCHESTRATOR_PARTITIONS=3
ORCHESTRATOR_NODE_ID=${HOSTNAME}
ORCHESTRATOR_PARTITION=${PARTITION_ID}

# Provider Configuration
PROVIDER_WORKERS=5
PROVIDER_MAX_RETRIES=3
PROVIDER_QUEUE_TIMEOUT=30

# Event Bus
EVENT_BUS_TYPE=redis
EVENT_BUS_CHANNEL_PREFIX=gleitzeit

# Monitoring
METRICS_ENABLED=true
METRICS_PORT=8080
HEALTH_CHECK_INTERVAL=10

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
LOG_OUTPUT=stdout
```

### 2. Redis Configuration

For production, use Redis Sentinel or Redis Cluster:

```yaml
# redis-cluster.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
data:
  redis.conf: |
    # Persistence
    save 900 1
    save 300 10
    save 60 10000
    appendonly yes
    
    # Memory management
    maxmemory 2gb
    maxmemory-policy allkeys-lru
    
    # Connection limits
    maxclients 10000
    timeout 300
    
    # Performance
    tcp-backlog 511
    tcp-keepalive 300
```

## Deployment Options

### Option 1: Kubernetes Deployment (Recommended)

#### Orchestrator Deployment

```yaml
# orchestrator-deployment.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: gleitzeit-orchestrator
spec:
  serviceName: orchestrator
  replicas: 3
  selector:
    matchLabels:
      app: gleitzeit-orchestrator
  template:
    metadata:
      labels:
        app: gleitzeit-orchestrator
    spec:
      containers:
      - name: orchestrator
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.orchestration.launcher"]
        env:
        - name: ORCHESTRATOR_PARTITIONS
          value: "3"
        - name: PARTITION_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.annotations['statefulset.kubernetes.io/pod-name']
        - name: REDIS_HOST
          value: redis-service
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
```

#### Provider Deployment

```yaml
# provider-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-provider
spec:
  replicas: 4
  selector:
    matchLabels:
      app: gleitzeit-provider
  template:
    metadata:
      labels:
        app: gleitzeit-provider
    spec:
      containers:
      - name: provider
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.providers.launcher"]
        env:
        - name: PROVIDER_WORKERS
          value: "5"
        - name: REDIS_HOST
          value: redis-service
        resources:
          requests:
            memory: "1Gi"
            cpu: "1000m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          periodSeconds: 10
```

#### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: provider-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-provider
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Pods
    pods:
      metric:
        name: pending_tasks
      target:
        type: AverageValue
        averageValue: "30"
```

### Option 2: Docker Compose

```yaml
# docker-compose.production.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    networks:
      - gleitzeit-net
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '2'
          memory: 2G

  orchestrator-0:
    image: gleitzeit:latest
    command: python -m gleitzeit.orchestration.launcher
    environment:
      ORCHESTRATOR_PARTITIONS: 3
      ORCHESTRATOR_PARTITION: 0
      REDIS_HOST: redis
    networks:
      - gleitzeit-net
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '1'
          memory: 1G

  orchestrator-1:
    image: gleitzeit:latest
    command: python -m gleitzeit.orchestration.launcher
    environment:
      ORCHESTRATOR_PARTITIONS: 3
      ORCHESTRATOR_PARTITION: 1
      REDIS_HOST: redis
    networks:
      - gleitzeit-net
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '1'
          memory: 1G

  orchestrator-2:
    image: gleitzeit:latest
    command: python -m gleitzeit.orchestration.launcher
    environment:
      ORCHESTRATOR_PARTITIONS: 3
      ORCHESTRATOR_PARTITION: 2
      REDIS_HOST: redis
    networks:
      - gleitzeit-net
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '1'
          memory: 1G

  provider:
    image: gleitzeit:latest
    command: python -m gleitzeit.providers.launcher
    environment:
      PROVIDER_WORKERS: 5
      REDIS_HOST: redis
    networks:
      - gleitzeit-net
    deploy:
      replicas: 4
      resources:
        limits:
          cpus: '2'
          memory: 2G

networks:
  gleitzeit-net:
    driver: overlay
    attachable: true

volumes:
  redis-data:
```

### Option 3: Systemd Services

For traditional Linux deployments:

```ini
# /etc/systemd/system/gleitzeit-orchestrator@.service
[Unit]
Description=Gleitzeit Orchestrator Partition %i
After=network.target redis.service

[Service]
Type=simple
User=gleitzeit
Group=gleitzeit
WorkingDirectory=/opt/gleitzeit
Environment="ORCHESTRATOR_PARTITIONS=3"
Environment="ORCHESTRATOR_PARTITION=%i"
Environment="REDIS_HOST=localhost"
ExecStart=/opt/gleitzeit/venv/bin/python -m gleitzeit.orchestration.launcher
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable services:
```bash
# Start 3 orchestrator partitions
systemctl enable gleitzeit-orchestrator@0
systemctl enable gleitzeit-orchestrator@1
systemctl enable gleitzeit-orchestrator@2
systemctl start gleitzeit-orchestrator@{0..2}

# Start provider services
systemctl enable gleitzeit-provider
systemctl start gleitzeit-provider
```

## Launcher Scripts

### Orchestrator Launcher

```python
# src/gleitzeit/orchestration/launcher.py
import os
import asyncio
import logging
from gleitzeit.orchestration.distributed_scheduler import DistributedOrchestrator
from gleitzeit.persistence.redis_backend import UnifiedRedisAdapter
from gleitzeit.events.base import EventBus

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

async def main():
    # Configuration from environment
    partitions = int(os.getenv('ORCHESTRATOR_PARTITIONS', '1'))
    partition = int(os.getenv('ORCHESTRATOR_PARTITION', '0'))
    node_id = os.getenv('ORCHESTRATOR_NODE_ID', f'orchestrator-{partition}')
    
    # Initialize components
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', '6379'))
    
    persistence = UnifiedRedisAdapter(
        host=redis_host,
        port=redis_port,
        password=os.getenv('REDIS_PASSWORD')
    )
    await persistence.initialize()
    
    event_bus = EventBus()
    
    # Create orchestrator
    orchestrator = DistributedOrchestrator(
        persistence=persistence,
        event_bus=event_bus,
        node_id=node_id,
        partition_key=partition if partitions > 1 else None,
        total_partitions=partitions
    )
    
    # Start orchestrator
    await orchestrator.start()
    logger.info(f"Orchestrator {node_id} started (partition {partition}/{partitions})")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
            # Log health status
            stats = await orchestrator.get_cluster_stats()
            logger.info(f"Cluster stats: {stats}")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await orchestrator.stop()
        await persistence.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### Provider Launcher

```python
# src/gleitzeit/providers/launcher.py
import os
import asyncio
import logging
from gleitzeit.orchestration.scalable_provider import ScalableProviderAdapter
from gleitzeit.persistence.redis_backend import UnifiedRedisAdapter
from gleitzeit.events.base import EventBus
from gleitzeit.providers import get_provider  # Your provider factory

logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

async def main():
    # Configuration from environment
    num_workers = int(os.getenv('PROVIDER_WORKERS', '5'))
    protocol = os.getenv('PROVIDER_PROTOCOL', 'native')
    node_id = os.getenv('PROVIDER_NODE_ID', f'provider-{os.getpid()}')
    
    # Initialize components
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', '6379'))
    
    persistence = UnifiedRedisAdapter(
        host=redis_host,
        port=redis_port,
        password=os.getenv('REDIS_PASSWORD')
    )
    await persistence.initialize()
    
    event_bus = EventBus()
    
    # Get provider for protocol
    provider = get_provider(protocol)
    
    # Create scalable adapter
    adapter = ScalableProviderAdapter(
        provider=provider,
        persistence=persistence,
        event_bus=event_bus,
        protocol=protocol,
        node_id=node_id,
        num_workers=num_workers
    )
    
    # Start adapter
    await adapter.start()
    logger.info(f"Provider adapter {node_id} started with {num_workers} workers")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
            # Log metrics
            metrics = await adapter.get_metrics()
            logger.info(f"Adapter metrics: {metrics}")
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await adapter.stop()
        await persistence.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

## Monitoring

### Prometheus Metrics

```python
# Add to your code
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Metrics
tasks_processed = Counter('gleitzeit_tasks_processed_total', 'Total processed tasks')
task_duration = Histogram('gleitzeit_task_duration_seconds', 'Task execution duration')
active_workers = Gauge('gleitzeit_active_workers', 'Number of active workers')

# Start metrics server
start_http_server(8080)
```

### Grafana Dashboard

Import the provided dashboard JSON:
```json
{
  "dashboard": {
    "title": "Gleitzeit Production Metrics",
    "panels": [
      {
        "title": "Task Throughput",
        "targets": [
          {
            "expr": "rate(gleitzeit_tasks_processed_total[5m])"
          }
        ]
      },
      {
        "title": "Task Duration (p95)",
        "targets": [
          {
            "expr": "histogram_quantile(0.95, gleitzeit_task_duration_seconds)"
          }
        ]
      },
      {
        "title": "Active Workers",
        "targets": [
          {
            "expr": "sum(gleitzeit_active_workers)"
          }
        ]
      }
    ]
  }
}
```

## Scaling Guidelines

### When to Scale Orchestrators
- **Add partitions** when workflow submission rate > 100/second
- **Monitor**: Redis CPU usage, event processing latency
- **Formula**: `partitions = ceil(workflows_per_second / 50)`

### When to Scale Providers
- **Add instances** when task queue depth > 100
- **Add workers** when CPU < 50% but queue growing
- **Monitor**: Task execution time, queue depth, CPU usage
- **Formula**: `providers = ceil(tasks_per_second / 20)`

## Performance Tuning

### Redis Optimization
```bash
# /etc/sysctl.conf
vm.overcommit_memory = 1
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535

# Apply settings
sysctl -p
```

### Python Optimization
```bash
# Use uvloop for better async performance
pip install uvloop

# In your launcher:
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
```

## Troubleshooting

### Common Issues

1. **Partition Imbalance**
   - Check hash distribution: `redis-cli --scan --pattern "workflow:*" | cut -d: -f3 | sort | uniq -c`
   - Solution: Increase partition count if > 20% imbalance

2. **Task Starvation**
   - Check queue depths: `redis-cli llen provider:queue:*`
   - Solution: Add more provider instances

3. **Memory Growth**
   - Check for workflow cleanup: `redis-cli info memory`
   - Solution: Implement TTL on completed workflows

### Health Checks

```bash
# Check orchestrator health
curl http://orchestrator:8080/health

# Check provider health  
curl http://provider:8080/health

# Check Redis
redis-cli ping

# Check queue depths
redis-cli --scan --pattern "provider:queue:*" | xargs -I{} redis-cli llen {}
```

## Security Considerations

1. **Redis Security**
   - Enable AUTH with strong password
   - Use TLS for connections
   - Restrict network access

2. **Application Security**
   - Run as non-root user
   - Use secrets management (Vault, K8s secrets)
   - Enable audit logging

3. **Network Security**
   - Use private networks
   - Enable firewall rules
   - Implement rate limiting

## Backup and Recovery

### Backup Strategy
```bash
# Daily Redis backup
redis-cli BGSAVE
aws s3 cp /var/lib/redis/dump.rdb s3://backup/redis/$(date +%Y%m%d).rdb

# Workflow state export
python -m gleitzeit.tools.export --output workflows.json
```

### Recovery Procedure
1. Stop all services
2. Restore Redis data
3. Start orchestrators first
4. Verify partition coverage
5. Start providers
6. Replay failed workflows if needed

## Production Checklist

- [ ] Redis cluster configured with persistence
- [ ] Environment variables configured
- [ ] TLS certificates installed
- [ ] Monitoring dashboards created
- [ ] Alerting rules configured
- [ ] Backup automation tested
- [ ] Load testing completed
- [ ] Runbooks documented
- [ ] Team trained on operations

## Support

For production support:
- Documentation: https://github.com/gleitzeit/docs
- Issues: https://github.com/gleitzeit/issues
- Slack: #gleitzeit-production