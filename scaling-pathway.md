# Gleitzeit Scaling Pathway
## From Single-Node to Distributed Multi-Engine Architecture

**Status: PLANNING** - Not yet implemented. Current system remains single-node but with improved architecture foundation for future scaling.

### Overview
This document outlines a practical pathway to scale Gleitzeit from a single-node system to a distributed, multi-engine architecture capable of handling enterprise workloads.

---

## 📊 Current Architecture (Single Node)

```mermaid
graph TB
    UI[Web UI :8080] --> API[API Server :8000]
    CLI[CLI] --> API
    API --> EE[Execution Engine]
    EE --> Q[Task Queue]
    EE --> P1[Python Provider]
    EE --> P2[Ollama Provider]
    EE --> P3[MCP Provider]
    API --> DB[(Persistence<br/>Redis/SQL)]
    EE --> DB
```

**Limitations:**
- Single point of failure
- Limited by single server resources
- No horizontal scaling
- Queue bottleneck
- No redundancy

---

## 🎯 Target Architecture (Distributed Multi-Engine)

```mermaid
graph TB
    LB[Load Balancer] --> API1[API Server 1]
    LB --> API2[API Server 2]
    LB --> API3[API Server N]
    
    API1 --> MQ[Message Queue<br/>Redis/RabbitMQ]
    API2 --> MQ
    API3 --> MQ
    
    MQ --> EE1[Engine 1<br/>General]
    MQ --> EE2[Engine 2<br/>Python]
    MQ --> EE3[Engine 3<br/>LLM]
    MQ --> EE4[Engine N<br/>Specialized]
    
    EE1 --> WP1[Worker Pool]
    EE2 --> WP2[Worker Pool]
    EE3 --> WP3[Worker Pool]
    EE4 --> WP4[Worker Pool]
    
    API1 --> DB[(Distributed DB<br/>PostgreSQL/Redis Cluster)]
    API2 --> DB
    API3 --> DB
    
    EE1 --> DB
    EE2 --> DB
    EE3 --> DB
    EE4 --> DB
    
    DB --> S3[Object Storage<br/>Results/Logs]
```

---

## 📈 Scaling Phases

### Phase 1: Prepare for Distribution (Current + Improvements)
**Timeline: 4-6 weeks**
**Complexity: Medium**

#### 1.1 Decouple Components
```python
# Current: Tight coupling
class GleitzeitClient:
    def __init__(self):
        self.engine = ExecutionEngine()  # Direct coupling
        self.queue = TaskQueue()         # Direct coupling

# Target: Loose coupling via interfaces
class GleitzeitClient:
    def __init__(self, engine_client: IEngineClient):
        self.engine_client = engine_client  # Interface-based
```

#### 1.2 Implement Task Serialization
```python
# src/gleitzeit/core/serialization.py
import pickle
import json
from typing import Any

class TaskSerializer:
    """Serialize tasks for network transport"""
    
    @staticmethod
    def serialize(task: Task) -> bytes:
        """Convert task to bytes for queue"""
        return pickle.dumps({
            'id': task.id,
            'workflow_id': task.workflow_id,
            'protocol': task.protocol,
            'method': task.method,
            'params': task.params,
            'dependencies': task.dependencies,
            'metadata': task.metadata
        })
    
    @staticmethod
    def deserialize(data: bytes) -> Task:
        """Reconstruct task from bytes"""
        task_data = pickle.loads(data)
        return Task(**task_data)
```

#### 1.3 Add Message Queue Abstraction
```python
# src/gleitzeit/queue/message_queue.py
from abc import ABC, abstractmethod

class MessageQueue(ABC):
    """Abstract message queue interface"""
    
    @abstractmethod
    async def publish(self, topic: str, message: bytes):
        """Publish message to topic"""
        pass
    
    @abstractmethod
    async def subscribe(self, topic: str, callback):
        """Subscribe to topic with callback"""
        pass

class RedisMessageQueue(MessageQueue):
    """Redis Pub/Sub implementation"""
    
    def __init__(self, redis_url: str):
        self.redis = aioredis.from_url(redis_url)
    
    async def publish(self, topic: str, message: bytes):
        await self.redis.publish(topic, message)
    
    async def subscribe(self, topic: str, callback):
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(topic)
        async for message in pubsub.listen():
            await callback(message['data'])
```

---

### Phase 2: Multiple Execution Engines (Same Node)
**Timeline: 3-4 weeks**
**Complexity: Medium**

#### 2.1 Engine Registry
```python
# src/gleitzeit/engine/registry.py
class EngineRegistry:
    """Manage multiple execution engines"""
    
    def __init__(self):
        self.engines = {}
        self.engine_capabilities = {}
    
    def register_engine(self, 
                       engine_id: str, 
                       engine: ExecutionEngine,
                       capabilities: List[str]):
        """Register an engine with its capabilities"""
        self.engines[engine_id] = engine
        self.engine_capabilities[engine_id] = capabilities
    
    def get_engine_for_task(self, task: Task) -> str:
        """Route task to appropriate engine"""
        # Route based on protocol
        if task.protocol.startswith('llm'):
            return 'llm-engine'
        elif task.protocol.startswith('python'):
            return 'python-engine'
        else:
            return 'general-engine'
```

#### 2.2 Multi-Engine Configuration
```yaml
# config/engines.yaml
engines:
  general-engine:
    type: general
    workers: 10
    max_tasks: 100
    protocols: ['*']
    
  python-engine:
    type: specialized
    workers: 20
    max_tasks: 200
    protocols: ['python/v1', 'python/v2']
    resources:
      cpu_cores: 4
      memory_gb: 8
      
  llm-engine:
    type: specialized
    workers: 5
    max_tasks: 50
    protocols: ['llm/v1', 'ollama/v1']
    resources:
      gpu_required: true
      gpu_memory_gb: 24
```

#### 2.3 Launch Multiple Engines
```python
# src/gleitzeit/engine/launcher.py
async def launch_multi_engine_system(config_path: str):
    """Launch multiple specialized engines"""
    
    config = load_config(config_path)
    registry = EngineRegistry()
    
    for engine_id, engine_config in config['engines'].items():
        # Create specialized engine
        engine = ExecutionEngine(
            engine_id=engine_id,
            worker_count=engine_config['workers'],
            max_tasks=engine_config['max_tasks']
        )
        
        # Register with capabilities
        registry.register_engine(
            engine_id=engine_id,
            engine=engine,
            capabilities=engine_config['protocols']
        )
        
        # Start engine in background
        asyncio.create_task(engine.start())
    
    # Start task router
    router = TaskRouter(registry)
    await router.start()
```

---

### Phase 3: Distributed Engines (Multiple Nodes)
**Timeline: 6-8 weeks**
**Complexity: High**

#### 3.1 Network Communication Layer
```python
# src/gleitzeit/network/rpc.py
import asyncio
import msgpack
from typing import Any

class EngineRPCServer:
    """RPC server for remote engine communication"""
    
    def __init__(self, engine: ExecutionEngine, port: int):
        self.engine = engine
        self.port = port
    
    async def start(self):
        """Start RPC server"""
        server = await asyncio.start_server(
            self.handle_client, 
            '0.0.0.0', 
            self.port
        )
        await server.serve_forever()
    
    async def handle_client(self, reader, writer):
        """Handle RPC requests"""
        while True:
            # Read message length
            length_bytes = await reader.read(4)
            if not length_bytes:
                break
            
            # Read message
            length = int.from_bytes(length_bytes, 'big')
            data = await reader.read(length)
            
            # Decode and process
            request = msgpack.unpackb(data)
            response = await self.process_request(request)
            
            # Send response
            response_data = msgpack.packb(response)
            writer.write(len(response_data).to_bytes(4, 'big'))
            writer.write(response_data)
            await writer.drain()

class EngineRPCClient:
    """RPC client for remote engine communication"""
    
    async def submit_task(self, engine_url: str, task: Task):
        """Submit task to remote engine"""
        host, port = engine_url.split(':')
        reader, writer = await asyncio.open_connection(host, int(port))
        
        # Serialize and send task
        request = {
            'method': 'submit_task',
            'params': TaskSerializer.serialize(task)
        }
        data = msgpack.packb(request)
        writer.write(len(data).to_bytes(4, 'big'))
        writer.write(data)
        await writer.drain()
        
        # Read response
        length_bytes = await reader.read(4)
        length = int.from_bytes(length_bytes, 'big')
        response_data = await reader.read(length)
        response = msgpack.unpackb(response_data)
        
        writer.close()
        await writer.wait_closed()
        
        return response
```

#### 3.2 Service Discovery
```python
# src/gleitzeit/discovery/consul.py
import consul

class ServiceDiscovery:
    """Service discovery for distributed engines"""
    
    def __init__(self, consul_host='localhost'):
        self.consul = consul.Consul(host=consul_host)
    
    def register_engine(self, engine_id: str, host: str, port: int, 
                       capabilities: List[str], health_check_url: str):
        """Register engine with service discovery"""
        self.consul.agent.service.register(
            name='gleitzeit-engine',
            service_id=engine_id,
            address=host,
            port=port,
            tags=capabilities,
            check=consul.Check.http(
                health_check_url,
                interval='10s',
                timeout='5s'
            )
        )
    
    def discover_engines(self, capability: str = None) -> List[str]:
        """Discover available engines"""
        _, services = self.consul.health.service(
            'gleitzeit-engine', 
            passing=True,
            tag=capability
        )
        
        return [
            f"{s['Service']['Address']}:{s['Service']['Port']}"
            for s in services
        ]
```

#### 3.3 Distributed Task Router
```python
# src/gleitzeit/routing/distributed_router.py
class DistributedTaskRouter:
    """Route tasks to distributed engines"""
    
    def __init__(self, discovery: ServiceDiscovery, queue: MessageQueue):
        self.discovery = discovery
        self.queue = queue
        self.rpc_client = EngineRPCClient()
        self.engine_loads = {}  # Track engine loads
    
    async def route_task(self, task: Task):
        """Route task to best available engine"""
        # Find suitable engines
        engines = self.discovery.discover_engines(task.protocol)
        
        if not engines:
            # Queue for later processing
            await self.queue.publish(f'pending:{task.protocol}', 
                                    TaskSerializer.serialize(task))
            return
        
        # Select least loaded engine
        selected = self.select_engine(engines)
        
        try:
            # Submit to remote engine
            result = await self.rpc_client.submit_task(selected, task)
            
            # Update load tracking
            self.update_load(selected, delta=1)
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to submit to {selected}: {e}")
            # Try next engine or requeue
            await self.handle_submission_failure(task, engines)
    
    def select_engine(self, engines: List[str]) -> str:
        """Select best engine based on load"""
        # Simple round-robin or least-loaded selection
        loads = [(e, self.engine_loads.get(e, 0)) for e in engines]
        loads.sort(key=lambda x: x[1])
        return loads[0][0]
```

---

### Phase 4: Kubernetes Deployment
**Timeline: 4-6 weeks**
**Complexity: High**

#### 4.1 Containerize Components
```dockerfile
# docker/engine.Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/gleitzeit ./gleitzeit

ENV ENGINE_TYPE=general
ENV ENGINE_ID=engine-${HOSTNAME}
ENV REDIS_URL=redis://redis:6379
ENV DATABASE_URL=postgresql://user:pass@postgres/gleitzeit

CMD ["python", "-m", "gleitzeit.engine.distributed", 
     "--type", "${ENGINE_TYPE}",
     "--id", "${ENGINE_ID}"]
```

#### 4.2 Kubernetes Manifests
```yaml
# k8s/engine-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-engine-general
spec:
  replicas: 3
  selector:
    matchLabels:
      app: gleitzeit-engine
      type: general
  template:
    metadata:
      labels:
        app: gleitzeit-engine
        type: general
    spec:
      containers:
      - name: engine
        image: gleitzeit/engine:latest
        env:
        - name: ENGINE_TYPE
          value: "general"
        - name: WORKER_COUNT
          value: "10"
        - name: REDIS_URL
          valueFrom:
            secretKeyRef:
              name: gleitzeit-secrets
              key: redis-url
        resources:
          requests:
            memory: "2Gi"
            cpu: "1"
          limits:
            memory: "4Gi"
            cpu: "2"
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
          initialDelaySeconds: 5
          periodSeconds: 5

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: gleitzeit-engine-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: gleitzeit-engine-general
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

#### 4.3 Kubernetes Operator
```python
# src/gleitzeit/operator/engine_operator.py
import kopf
import kubernetes

@kopf.on.create('gleitzeit.io', 'v1', 'engines')
async def create_engine(spec, name, namespace, **kwargs):
    """Create a new Gleitzeit engine"""
    
    k8s_apps = kubernetes.client.AppsV1Api()
    
    # Create deployment for engine
    deployment = kubernetes.client.V1Deployment(
        metadata=kubernetes.client.V1ObjectMeta(name=f"engine-{name}"),
        spec=kubernetes.client.V1DeploymentSpec(
            replicas=spec.get('replicas', 1),
            selector=kubernetes.client.V1LabelSelector(
                match_labels={"engine": name}
            ),
            template=kubernetes.client.V1PodTemplateSpec(
                metadata=kubernetes.client.V1ObjectMeta(
                    labels={"engine": name}
                ),
                spec=kubernetes.client.V1PodSpec(
                    containers=[
                        kubernetes.client.V1Container(
                            name="engine",
                            image=spec.get('image', 'gleitzeit/engine:latest'),
                            env=[
                                kubernetes.client.V1EnvVar(
                                    name="ENGINE_TYPE",
                                    value=spec.get('type', 'general')
                                ),
                                kubernetes.client.V1EnvVar(
                                    name="PROTOCOLS",
                                    value=','.join(spec.get('protocols', []))
                                )
                            ]
                        )
                    ]
                )
            )
        )
    )
    
    k8s_apps.create_namespaced_deployment(
        namespace=namespace,
        body=deployment
    )
    
    return {'message': f'Engine {name} created'}

@kopf.on.field('gleitzeit.io', 'v1', 'engines', field='spec.replicas')
async def scale_engine(old, new, name, namespace, **kwargs):
    """Scale engine replicas"""
    k8s_apps = kubernetes.client.AppsV1Api()
    
    k8s_apps.patch_namespaced_deployment_scale(
        name=f"engine-{name}",
        namespace=namespace,
        body={'spec': {'replicas': new}}
    )
    
    return {'scaled': f'{old} -> {new}'}
```

---

## 🔧 Implementation Components

### Component 1: Distributed Lock Manager
```python
# src/gleitzeit/coordination/locks.py
import aioredis
import asyncio
from contextlib import asynccontextmanager

class DistributedLock:
    """Distributed lock using Redis"""
    
    def __init__(self, redis: aioredis.Redis, key: str, timeout: int = 30):
        self.redis = redis
        self.key = f"lock:{key}"
        self.timeout = timeout
        self.token = None
    
    async def acquire(self, blocking: bool = True) -> bool:
        """Acquire lock"""
        import uuid
        self.token = str(uuid.uuid4())
        
        while True:
            acquired = await self.redis.set(
                self.key, 
                self.token, 
                nx=True, 
                ex=self.timeout
            )
            
            if acquired:
                return True
            
            if not blocking:
                return False
            
            await asyncio.sleep(0.1)
    
    async def release(self):
        """Release lock if we own it"""
        if self.token:
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            await self.redis.eval(lua_script, 1, self.key, self.token)
    
    @asynccontextmanager
    async def __aenter__(self):
        await self.acquire()
        yield self
    
    async def __aexit__(self, *args):
        await self.release()
```

### Component 2: Health Checks
```python
# src/gleitzeit/health/checks.py
from typing import Dict, Any
import psutil

class EngineHealthCheck:
    """Health checks for execution engines"""
    
    def __init__(self, engine):
        self.engine = engine
    
    async def check(self) -> Dict[str, Any]:
        """Comprehensive health check"""
        return {
            'status': 'healthy' if self.is_healthy() else 'unhealthy',
            'engine_id': self.engine.engine_id,
            'metrics': {
                'active_tasks': self.engine.active_tasks,
                'queued_tasks': len(self.engine.task_queue),
                'worker_count': self.engine.worker_count,
                'cpu_percent': psutil.cpu_percent(),
                'memory_percent': psutil.virtual_memory().percent,
                'disk_usage': psutil.disk_usage('/').percent
            },
            'capabilities': self.engine.capabilities,
            'uptime': self.engine.uptime()
        }
    
    def is_healthy(self) -> bool:
        """Check if engine is healthy"""
        # Check various health criteria
        if self.engine.active_tasks > self.engine.max_tasks * 0.95:
            return False  # Overloaded
        
        if psutil.virtual_memory().percent > 90:
            return False  # Memory pressure
        
        if not self.engine.is_accepting_tasks():
            return False  # Not accepting new work
        
        return True
```

### Component 3: Load Balancing
```python
# src/gleitzeit/loadbalancer/algorithms.py
from abc import ABC, abstractmethod
from typing import List, Optional
import random

class LoadBalancer(ABC):
    """Abstract load balancer"""
    
    @abstractmethod
    def select(self, engines: List[str]) -> Optional[str]:
        """Select an engine"""
        pass

class RoundRobinBalancer(LoadBalancer):
    """Round-robin load balancing"""
    
    def __init__(self):
        self.current = 0
    
    def select(self, engines: List[str]) -> Optional[str]:
        if not engines:
            return None
        
        selected = engines[self.current % len(engines)]
        self.current += 1
        return selected

class LeastConnectionsBalancer(LoadBalancer):
    """Least connections load balancing"""
    
    def __init__(self, connection_tracker):
        self.tracker = connection_tracker
    
    def select(self, engines: List[str]) -> Optional[str]:
        if not engines:
            return None
        
        # Get connection counts
        counts = [(e, self.tracker.get_count(e)) for e in engines]
        counts.sort(key=lambda x: x[1])
        
        return counts[0][0]

class WeightedRandomBalancer(LoadBalancer):
    """Weighted random load balancing"""
    
    def __init__(self, weights: Dict[str, float]):
        self.weights = weights
    
    def select(self, engines: List[str]) -> Optional[str]:
        if not engines:
            return None
        
        # Filter to available engines
        available_weights = {
            e: self.weights.get(e, 1.0) 
            for e in engines
        }
        
        # Weighted random selection
        total = sum(available_weights.values())
        rand = random.uniform(0, total)
        
        cumulative = 0
        for engine, weight in available_weights.items():
            cumulative += weight
            if rand <= cumulative:
                return engine
        
        return engines[-1]  # Fallback
```

---

## 📈 Performance Targets

### Single Node (Current)
- Tasks/second: 10-50
- Concurrent workflows: 10-20
- Max workers: 20
- Latency: 100-500ms

### Phase 2 (Multi-Engine, Same Node)
- Tasks/second: 100-200
- Concurrent workflows: 50-100
- Max workers: 100
- Latency: 50-200ms

### Phase 3 (Distributed)
- Tasks/second: 1,000-5,000
- Concurrent workflows: 500-1,000
- Max workers: 1,000+
- Latency: 20-100ms

### Phase 4 (Kubernetes)
- Tasks/second: 10,000+
- Concurrent workflows: 5,000+
- Max workers: Auto-scaling
- Latency: 10-50ms

---

## 🚨 Key Challenges & Solutions

### Challenge 1: State Consistency
**Problem:** Multiple engines may have conflicting state
**Solution:** 
- Use distributed locks for critical sections
- Implement optimistic concurrency control
- Use event sourcing for state changes

### Challenge 2: Network Partitions
**Problem:** Engines may become isolated
**Solution:**
- Implement circuit breakers
- Use retry with exponential backoff
- Maintain local task queues for resilience

### Challenge 3: Task Affinity
**Problem:** Some tasks must run on specific engines
**Solution:**
- Implement task routing rules
- Use labels and selectors
- Support sticky sessions where needed

### Challenge 4: Monitoring at Scale
**Problem:** Hard to track tasks across engines
**Solution:**
- Implement distributed tracing (OpenTelemetry)
- Central log aggregation (ELK stack)
- Metrics collection (Prometheus)

---

## 🗓️ Migration Timeline

### Month 1-2: Foundation
- Decouple components
- Add serialization
- Implement message queue abstraction
- Set up testing infrastructure

### Month 3-4: Multi-Engine
- Implement engine registry
- Add specialized engines
- Create task routing logic
- Test on single node

### Month 5-7: Distribution
- Add network communication
- Implement service discovery
- Create distributed router
- Test across multiple nodes

### Month 8-9: Kubernetes
- Containerize components
- Create Kubernetes manifests
- Implement operator
- Set up auto-scaling

### Month 10-12: Production Hardening
- Performance testing
- Chaos engineering
- Documentation
- Training

---

## 📝 Configuration Examples

### Multi-Engine Configuration
```yaml
# config/multi-engine.yaml
gleitzeit:
  mode: multi-engine
  
  engines:
    - id: general-001
      type: general
      workers: 20
      protocols: ["*"]
      
    - id: python-001
      type: python
      workers: 50
      protocols: ["python/v1"]
      env:
        PYTHON_EXECUTOR: subprocess
        
    - id: llm-001
      type: llm
      workers: 10
      protocols: ["llm/v1", "ollama/v1"]
      resources:
        gpu: required
        
  routing:
    strategy: least-loaded
    sticky_sessions: true
    affinity_rules:
      - pattern: "*.gpu_required"
        engine: llm-001
```

### Distributed Configuration
```yaml
# config/distributed.yaml
gleitzeit:
  mode: distributed
  
  cluster:
    name: production
    region: us-west-2
    
  discovery:
    type: consul
    consul_host: consul.service.consul
    
  message_queue:
    type: rabbitmq
    url: amqp://user:pass@rabbitmq:5672
    
  persistence:
    type: postgres
    url: postgresql://user:pass@postgres/gleitzeit
    pool_size: 20
    
  object_storage:
    type: s3
    bucket: gleitzeit-artifacts
    region: us-west-2
```

---

## 🎯 Success Metrics

### Operational Metrics
- Engine utilization > 70%
- Task success rate > 99.9%
- P95 latency < 100ms
- Zero data loss
- 99.99% availability

### Business Metrics
- 10x throughput increase
- 50% cost reduction per task
- 90% reduction in manual interventions
- Support for 1000+ concurrent users
- Multi-region deployment capability

---

## 📚 References

### Technologies to Evaluate
- **Message Queues**: RabbitMQ, Apache Kafka, NATS
- **Service Mesh**: Istio, Linkerd, Consul Connect
- **Orchestration**: Kubernetes, Nomad, Docker Swarm
- **Monitoring**: Prometheus, Grafana, Jaeger
- **Service Discovery**: Consul, Etcd, Zookeeper

### Similar Systems to Study
- Apache Airflow Celery Executor
- Temporal.io Architecture
- Prefect Cloud
- Argo Workflows
- Dagster Cloud

---

## Conclusion

This scaling pathway provides a practical, incremental approach to evolving Gleitzeit from a single-node system to a distributed, enterprise-ready workflow orchestration platform. Each phase builds on the previous one, allowing for validation and learning at each step while maintaining backward compatibility where possible.