# Gleitzeit Cluster Orchestration Strategy
## Complete Guide for Distributed Deployment and Management

**Date:** 2025-08-30  
**Scope:** Full cluster orchestration architecture

---

## Executive Summary

This document outlines three orchestration strategies for Gleitzeit clusters:

1. **Kubernetes-Native** (Recommended for production)
2. **Docker Swarm** (Simpler alternative)
3. **Self-Managed** (Maximum control, Redis-based)

Each approach provides service discovery, scaling, health monitoring, and failover capabilities with different complexity/feature tradeoffs.

---

## Cluster Components Overview

```
Gleitzeit Cluster Components:
├── API Gateway Layer (3+ instances)
├── Workflow Coordinators (3+ instances)
├── Execution Engines (5-20 instances)
├── Retry Processors (2 instances)
├── Provider Pools (N instances)
├── Redis Cluster (3+ nodes)
└── Monitoring Stack (Prometheus, Grafana)
```

---

## Option 1: Kubernetes-Native Orchestration (Recommended)

### Architecture

```yaml
┌─────────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Ingress Controller                                        │
│       ↓                                                     │
│  ┌─────────────────────────────────────────────┐          │
│  │  Namespace: gleitzeit-prod                  │          │
│  ├─────────────────────────────────────────────┤          │
│  │                                             │          │
│  │  API Gateway (Deployment)                   │          │
│  │  ├── Replicas: 3                           │          │
│  │  ├── Service: LoadBalancer                 │          │
│  │  └── HPA: 3-10 pods                        │          │
│  │                                             │          │
│  │  Workflow Coordinator (StatefulSet)         │          │
│  │  ├── Replicas: 3                           │          │
│  │  ├── Service: Headless                     │          │
│  │  └── PVC: Leader election state            │          │
│  │                                             │          │
│  │  Execution Engine (Deployment)              │          │
│  │  ├── Replicas: 5-20                        │          │
│  │  ├── Service: ClusterIP                    │          │
│  │  └── HPA: CPU/Memory based                 │          │
│  │                                             │          │
│  │  Redis (StatefulSet or Operator)           │          │
│  │  ├── Redis Cluster: 3 masters, 3 replicas  │          │
│  │  └── PVC: Data persistence                 │          │
│  └─────────────────────────────────────────────┤          │
└─────────────────────────────────────────────────────────────┘
```

### Kubernetes Manifests

#### 1. Namespace and ConfigMap
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: gleitzeit-prod
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: gleitzeit-config
  namespace: gleitzeit-prod
data:
  REDIS_URL: "redis://redis-cluster:6379"
  LOG_LEVEL: "INFO"
  MAX_CONCURRENT_TASKS: "100"
  WORKER_HEARTBEAT_INTERVAL: "10"
```

#### 2. API Gateway Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-gateway
  namespace: gleitzeit-prod
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api-gateway
  template:
    metadata:
      labels:
        app: api-gateway
    spec:
      containers:
      - name: api
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.api.main"]
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: gleitzeit-config
              key: REDIS_URL
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: api-gateway
  namespace: gleitzeit-prod
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8000
  selector:
    app: api-gateway
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-gateway-hpa
  namespace: gleitzeit-prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

#### 3. Workflow Coordinator StatefulSet
```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: workflow-coordinator
  namespace: gleitzeit-prod
spec:
  serviceName: workflow-coordinator
  replicas: 3
  selector:
    matchLabels:
      app: workflow-coordinator
  template:
    metadata:
      labels:
        app: workflow-coordinator
    spec:
      containers:
      - name: coordinator
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.coordinator.main"]
        env:
        - name: COORDINATOR_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: gleitzeit-config
              key: REDIS_URL
        - name: LEADER_ELECTION_ENABLED
          value: "true"
        ports:
        - containerPort: 9090
          name: metrics
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        volumeMounts:
        - name: coordinator-state
          mountPath: /data
  volumeClaimTemplates:
  - metadata:
      name: coordinator-state
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
---
apiVersion: v1
kind: Service
metadata:
  name: workflow-coordinator
  namespace: gleitzeit-prod
spec:
  clusterIP: None  # Headless service for StatefulSet
  ports:
  - port: 9090
    name: metrics
  selector:
    app: workflow-coordinator
```

#### 4. Execution Engine Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: execution-engine
  namespace: gleitzeit-prod
spec:
  replicas: 5
  selector:
    matchLabels:
      app: execution-engine
  template:
    metadata:
      labels:
        app: execution-engine
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
    spec:
      containers:
      - name: engine
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.engine.main"]
        env:
        - name: ENGINE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: gleitzeit-config
              key: REDIS_URL
        - name: MAX_CONCURRENT_TASKS
          valueFrom:
            configMapKeyRef:
              name: gleitzeit-config
              key: MAX_CONCURRENT_TASKS
        ports:
        - containerPort: 9090
          name: metrics
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
        livenessProbe:
          exec:
            command:
            - python
            - -c
            - "import sys; from gleitzeit.health import check_engine; sys.exit(0 if check_engine() else 1)"
          initialDelaySeconds: 30
          periodSeconds: 30
        readinessProbe:
          exec:
            command:
            - python
            - -c
            - "import sys; from gleitzeit.health import engine_ready; sys.exit(0 if engine_ready() else 1)"
          initialDelaySeconds: 10
          periodSeconds: 10
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: execution-engine-hpa
  namespace: gleitzeit-prod
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: execution-engine
  minReplicas: 5
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60
  - type: Pods
    pods:
      metric:
        name: pending_tasks
      target:
        type: AverageValue
        averageValue: "30"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
      - type: Percent
        value: 100
        periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
```

#### 5. Redis Cluster (Using Operator)
```yaml
apiVersion: redis.redis.opstreelabs.in/v1beta1
kind: RedisCluster
metadata:
  name: redis-cluster
  namespace: gleitzeit-prod
spec:
  clusterSize: 3
  clusterVersion: v7
  persistenceEnabled: true
  storage:
    volumeClaimTemplate:
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 10Gi
  redisConfig:
    maxmemory: 2gb
    maxmemory-policy: allkeys-lru
  resources:
    requests:
      cpu: 101m
      memory: 128Mi
    limits:
      cpu: 101m
      memory: 128Mi
```

### Service Discovery in Kubernetes

```python
# Automatic service discovery using Kubernetes DNS
class KubernetesServiceDiscovery:
    def __init__(self):
        # Load in-cluster config
        config.load_incluster_config()
        self.v1 = client.CoreV1Api()
        self.namespace = open(
            "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        ).read()
    
    async def discover_engines(self) -> List[str]:
        """Discover all execution engine pods"""
        pods = self.v1.list_namespaced_pod(
            namespace=self.namespace,
            label_selector="app=execution-engine"
        )
        
        engine_endpoints = []
        for pod in pods.items:
            if pod.status.phase == "Running":
                engine_endpoints.append(
                    f"{pod.status.pod_ip}:9090"
                )
        
        return engine_endpoints
    
    async def get_coordinator_leader(self, workflow_id: str) -> str:
        """Get leader coordinator for workflow"""
        # Use headless service for StatefulSet
        # workflow-coordinator-0.workflow-coordinator.gleitzeit-prod.svc.cluster.local
        coordinator_index = hash(workflow_id) % 3  # Number of replicas
        return f"workflow-coordinator-{coordinator_index}.workflow-coordinator"
```

---

## Option 2: Docker Swarm Orchestration

### Architecture

```yaml
┌─────────────────────────────────────────────────────┐
│                 Docker Swarm Cluster                 │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Stack: gleitzeit                                  │
│  ├── api_gateway (3 replicas)                      │
│  ├── workflow_coordinator (3 replicas)             │
│  ├── execution_engine (5-20 replicas)              │
│  ├── retry_processor (2 replicas)                  │
│  └── redis (1 replica + volume)                    │
│                                                     │
│  Networks:                                         │
│  ├── frontend (external)                           │
│  └── backend (internal)                            │
│                                                     │
│  Volumes:                                          │
│  ├── redis-data                                    │
│  └── coordinator-state                             │
└─────────────────────────────────────────────────────┘
```

### Docker Stack Configuration

```yaml
# docker-stack.yml
version: '3.8'

services:
  api_gateway:
    image: gleitzeit:latest
    command: python -m gleitzeit.api.main
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
      placement:
        constraints:
          - node.role == worker
    networks:
      - frontend
      - backend
    ports:
      - "80:8000"
    environment:
      REDIS_URL: redis://redis:6379
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  workflow_coordinator:
    image: gleitzeit:latest
    command: python -m gleitzeit.coordinator.main
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
    networks:
      - backend
    environment:
      REDIS_URL: redis://redis:6379
      COORDINATOR_ID: "{{.Task.Name}}"
    volumes:
      - coordinator-state:/data

  execution_engine:
    image: gleitzeit:latest
    command: python -m gleitzeit.engine.main
    deploy:
      replicas: 5
      update_config:
        parallelism: 2
        delay: 10s
      restart_policy:
        condition: on-failure
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G
    networks:
      - backend
    environment:
      REDIS_URL: redis://redis:6379
      ENGINE_ID: "{{.Task.Name}}"
      MAX_CONCURRENT_TASKS: 20

  redis:
    image: redis:7-alpine
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.labels.redis == true
    networks:
      - backend
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes

networks:
  frontend:
    external: true
  backend:
    driver: overlay
    internal: true

volumes:
  redis-data:
    driver: local
  coordinator-state:
    driver: local
```

### Swarm Service Discovery

```python
class SwarmServiceDiscovery:
    def __init__(self):
        self.docker = docker.DockerClient(
            base_url='unix://var/run/docker.sock'
        )
    
    async def discover_engines(self) -> List[str]:
        """Discover execution engine tasks"""
        service = self.docker.services.get('gleitzeit_execution_engine')
        tasks = service.tasks()
        
        engine_endpoints = []
        for task in tasks:
            if task['Status']['State'] == 'running':
                # Use task name as engine ID
                engine_id = task['Status']['ContainerStatus']['ContainerID'][:12]
                # Swarm internal DNS
                engine_endpoints.append(f"{engine_id}:9090")
        
        return engine_endpoints
```

---

## Option 3: Self-Managed Orchestration (Redis-Based)

### Architecture

```python
┌─────────────────────────────────────────────────────┐
│           Self-Managed Cluster (Redis-Based)        │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Cluster Manager (1 active, 1 standby)             │
│  ├── Service registry                              │
│  ├── Health monitoring                             │
│  ├── Auto-scaling decisions                        │
│  └── Leader election                               │
│                                                     │
│  Service Registry (Redis)                          │
│  ├── services:api:{id} → endpoint, health, load    │
│  ├── services:engine:{id} → endpoint, capacity     │
│  ├── services:coordinator:{id} → endpoint, leader  │
│  └── cluster:topology → current cluster state      │
│                                                     │
│  Health Monitoring                                 │
│  ├── Heartbeat tracking                            │
│  ├── Performance metrics                           │
│  └── Failure detection                             │
└─────────────────────────────────────────────────────┘
```

### Implementation

#### 1. Cluster Manager
```python
class GleitzeitClusterManager:
    """Self-managed cluster orchestration"""
    
    def __init__(self, manager_id: str, redis: Redis):
        self.manager_id = manager_id
        self.redis = redis
        self.is_leader = False
        self.services = {}
        
    async def run(self):
        """Main orchestration loop"""
        # Try to become cluster manager leader
        await self.elect_leader()
        
        while True:
            if self.is_leader:
                await self.manage_cluster()
            else:
                await self.standby_mode()
            
            await asyncio.sleep(1)
    
    async def elect_leader(self):
        """Elect cluster manager leader"""
        key = "cluster:manager:leader"
        self.is_leader = await self.redis.set(
            key,
            self.manager_id,
            nx=True,
            ex=30
        )
        
        if self.is_leader:
            # Start lease renewal
            asyncio.create_task(self.renew_leadership())
    
    async def manage_cluster(self):
        """Active cluster management"""
        # 1. Update service registry
        await self.update_service_registry()
        
        # 2. Check service health
        await self.check_service_health()
        
        # 3. Make scaling decisions
        await self.auto_scale_services()
        
        # 4. Rebalance workloads
        await self.rebalance_workloads()
    
    async def update_service_registry(self):
        """Maintain service registry"""
        # Get all registered services
        pattern = "services:*"
        async for key in self.redis.scan_iter(pattern):
            service_data = await self.redis.hgetall(key)
            
            # Check if heartbeat is fresh
            last_heartbeat = float(service_data.get('heartbeat', 0))
            if time.time() - last_heartbeat > 30:
                # Mark as unhealthy
                await self.redis.hset(key, 'status', 'unhealthy')
                await self.handle_unhealthy_service(key)
    
    async def auto_scale_services(self):
        """Auto-scale based on load"""
        # Get cluster metrics
        metrics = await self.get_cluster_metrics()
        
        # Execution engines
        engine_load = metrics['engine_load_avg']
        if engine_load > 80:
            await self.scale_up_engines()
        elif engine_load < 20:
            await self.scale_down_engines()
        
        # API gateways
        api_latency = metrics['api_latency_p99']
        if api_latency > 500:  # ms
            await self.scale_up_api()
    
    async def scale_up_engines(self):
        """Scale up execution engines"""
        # Signal to infrastructure to start new engine
        await self.redis.publish(
            "cluster:scaling:engines",
            json.dumps({
                'action': 'scale_up',
                'count': 2,
                'timestamp': time.time()
            })
        )
    
    async def rebalance_workloads(self):
        """Rebalance work across engines"""
        # Get engine loads
        engines = await self.get_engine_loads()
        
        # Find imbalanced engines
        avg_load = sum(engines.values()) / len(engines)
        for engine_id, load in engines.items():
            if load > avg_load * 1.5:
                # Trigger work stealing
                await self.trigger_work_stealing(engine_id)
```

#### 2. Service Self-Registration
```python
class ServiceRegistration:
    """Self-registration for services"""
    
    def __init__(
        self,
        service_type: str,
        service_id: str,
        redis: Redis
    ):
        self.service_type = service_type
        self.service_id = service_id
        self.redis = redis
        self.key = f"services:{service_type}:{service_id}"
        
    async def register(self):
        """Register service with cluster"""
        service_info = {
            'service_id': self.service_id,
            'service_type': self.service_type,
            'endpoint': f"{self.get_ip()}:{self.get_port()}",
            'started_at': time.time(),
            'status': 'healthy',
            'heartbeat': time.time(),
            'capabilities': json.dumps(self.get_capabilities()),
            'capacity': self.get_capacity(),
            'current_load': 0
        }
        
        await self.redis.hset(self.key, mapping=service_info)
        
        # Start heartbeat
        asyncio.create_task(self.heartbeat_loop())
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats"""
        while True:
            await self.redis.hset(
                self.key,
                mapping={
                    'heartbeat': time.time(),
                    'current_load': self.get_current_load(),
                    'status': 'healthy'
                }
            )
            await asyncio.sleep(10)
    
    async def deregister(self):
        """Deregister on shutdown"""
        await self.redis.delete(self.key)
```

#### 3. Service Discovery
```python
class ClusterServiceDiscovery:
    """Discover services in cluster"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        self.cache = {}
        self.cache_ttl = 5  # seconds
        
    async def discover_service(
        self,
        service_type: str,
        capability: str = None
    ) -> List[ServiceInfo]:
        """Discover available services"""
        # Check cache
        cache_key = f"{service_type}:{capability}"
        if cache_key in self.cache:
            cached_time, services = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return services
        
        # Query Redis
        pattern = f"services:{service_type}:*"
        services = []
        
        async for key in self.redis.scan_iter(pattern):
            service_data = await self.redis.hgetall(key)
            
            # Check if healthy
            if service_data.get('status') != 'healthy':
                continue
            
            # Check capability if specified
            if capability:
                capabilities = json.loads(
                    service_data.get('capabilities', '[]')
                )
                if capability not in capabilities:
                    continue
            
            services.append(ServiceInfo(**service_data))
        
        # Update cache
        self.cache[cache_key] = (time.time(), services)
        
        return services
    
    async def get_least_loaded(
        self,
        service_type: str
    ) -> Optional[ServiceInfo]:
        """Get least loaded service instance"""
        services = await self.discover_service(service_type)
        
        if not services:
            return None
        
        return min(
            services,
            key=lambda s: float(s.current_load) / float(s.capacity)
        )
```

### Deployment Scripts

#### 1. Cluster Bootstrap
```bash
#!/bin/bash
# bootstrap-cluster.sh

# Start Redis first
docker run -d \
  --name redis-cluster \
  -p 6379:6379 \
  redis:7-alpine

# Start cluster manager (primary)
docker run -d \
  --name cluster-manager-1 \
  --env MANAGER_ID=manager-1 \
  --env REDIS_URL=redis://redis-cluster:6379 \
  gleitzeit:latest \
  python -m gleitzeit.cluster.manager

# Start cluster manager (standby)
docker run -d \
  --name cluster-manager-2 \
  --env MANAGER_ID=manager-2 \
  --env REDIS_URL=redis://redis-cluster:6379 \
  gleitzeit:latest \
  python -m gleitzeit.cluster.manager

# Start initial services
for i in {1..3}; do
  docker run -d \
    --name api-gateway-$i \
    --env SERVICE_ID=api-$i \
    --env REDIS_URL=redis://redis-cluster:6379 \
    -p 800$i:8000 \
    gleitzeit:latest \
    python -m gleitzeit.api.main
done

for i in {1..5}; do
  docker run -d \
    --name execution-engine-$i \
    --env ENGINE_ID=engine-$i \
    --env REDIS_URL=redis://redis-cluster:6379 \
    gleitzeit:latest \
    python -m gleitzeit.engine.main
done
```

#### 2. Scaling Script
```python
#!/usr/bin/env python
# scale-cluster.py

import asyncio
import sys
from gleitzeit.cluster import ClusterManager

async def scale_component(component: str, replicas: int):
    """Scale cluster component"""
    manager = ClusterManager()
    
    if component == "engine":
        await manager.scale_engines(replicas)
    elif component == "api":
        await manager.scale_api_gateways(replicas)
    elif component == "coordinator":
        await manager.scale_coordinators(replicas)
    else:
        print(f"Unknown component: {component}")
        return
    
    print(f"Scaled {component} to {replicas} replicas")

if __name__ == "__main__":
    component = sys.argv[1]
    replicas = int(sys.argv[2])
    asyncio.run(scale_component(component, replicas))
```

---

## Comparison Matrix

| Feature | Kubernetes | Docker Swarm | Self-Managed |
|---------|------------|--------------|--------------|
| **Complexity** | High | Medium | High |
| **Setup Time** | Days | Hours | Days |
| **Scaling** | Excellent (HPA) | Good (Manual) | Custom |
| **Service Discovery** | Native DNS | Native DNS | Redis-based |
| **Health Checks** | Native | Native | Custom |
| **Load Balancing** | Ingress/Service | Routing Mesh | Custom |
| **Persistent Storage** | PVC | Volumes | External |
| **Monitoring** | Prometheus Native | Basic | Custom |
| **Multi-Region** | Yes | Limited | Custom |
| **Learning Curve** | Steep | Moderate | Depends |
| **Community** | Huge | Large | None |
| **Cost** | Higher | Lower | Variable |

---

## Monitoring & Observability

### Metrics Collection
```python
class ClusterMetrics:
    """Cluster-wide metrics collection"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
        
    async def collect_metrics(self):
        """Collect metrics from all services"""
        metrics = {
            'timestamp': time.time(),
            'services': {},
            'cluster': {}
        }
        
        # Collect per-service metrics
        pattern = "services:*"
        async for key in self.redis.scan_iter(pattern):
            service_data = await self.redis.hgetall(key)
            service_id = service_data['service_id']
            
            metrics['services'][service_id] = {
                'status': service_data['status'],
                'load': float(service_data.get('current_load', 0)),
                'capacity': float(service_data.get('capacity', 100)),
                'uptime': time.time() - float(service_data['started_at'])
            }
        
        # Calculate cluster metrics
        metrics['cluster'] = {
            'total_services': len(metrics['services']),
            'healthy_services': sum(
                1 for s in metrics['services'].values()
                if s['status'] == 'healthy'
            ),
            'avg_load': sum(
                s['load'] for s in metrics['services'].values()
            ) / len(metrics['services']),
            'total_capacity': sum(
                s['capacity'] for s in metrics['services'].values()
            )
        }
        
        # Store in time-series
        await self.redis.zadd(
            "metrics:cluster",
            {json.dumps(metrics): time.time()}
        )
        
        return metrics
```

### Prometheus Integration
```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'gleitzeit-cluster'
    kubernetes_sd_configs:
    - role: pod
      namespaces:
        names:
        - gleitzeit-prod
    relabel_configs:
    - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
      action: keep
      regex: true
    - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
      action: replace
      target_label: __address__
      regex: ([^:]+)(?::\d+)?;(\d+)
      replacement: $1:$2
```

---

## Disaster Recovery

### Backup Strategy
```python
class ClusterBackup:
    """Backup cluster state"""
    
    async def backup_cluster_state(self):
        """Backup critical cluster state"""
        backup = {
            'timestamp': time.time(),
            'version': '1.0',
            'services': {},
            'workflows': {},
            'configuration': {}
        }
        
        # Backup service registry
        pattern = "services:*"
        async for key in self.redis.scan_iter(pattern):
            backup['services'][key] = await self.redis.hgetall(key)
        
        # Backup workflow states
        pattern = "workflow:*:state"
        async for key in self.redis.scan_iter(pattern):
            backup['workflows'][key] = await self.redis.hgetall(key)
        
        # Save to S3 or similar
        await self.save_backup(backup)
```

### Recovery Procedures
1. **Service Failure**: Automatic restart via orchestrator
2. **Node Failure**: Workload redistribution
3. **Redis Failure**: Restore from backup + replay events
4. **Complete Cluster Failure**: Bootstrap from backup

---

## Recommendations

### For Production (>100 workflows/hour)
**Use Kubernetes** with:
- Managed Kubernetes (EKS/GKE/AKS)
- Redis Operator for cluster management
- Prometheus + Grafana for monitoring
- Istio for service mesh (optional)

### For Development/Small Scale
**Use Docker Swarm** with:
- 3-node Swarm cluster
- Single Redis with persistence
- Basic monitoring

### For Maximum Control
**Use Self-Managed** with:
- Custom orchestration logic
- Redis-based coordination
- Tailored scaling policies

---

**Document Status:** Complete  
**Complexity:** High  
**Implementation Time:** 1-4 weeks depending on approach