# Worker Architecture Audit - Current State (Revised)

## Executive Summary
**Finding: Gleitzeit API uses a pool of GleitzeitClient instances as "workers" - each client is a complete execution unit that processes workflows.**

## Current Architecture

### 1. Request Flow (Client Pool as Workers)
```
API Request
    ↓
ClientPool.acquire() - Gets available client
    ↓
GleitzeitClient (complete execution unit)
    ├── NativeAdapter
    ├── ExecutionEngine 
    ├── TaskExecutor
    └── Providers (via Registry/PoolingAdapter)
    ↓
ClientPool.release() - Returns client to pool
```

### 2. Core Components

#### **ClientPool** (`src/gleitzeit/api/dependencies.py`)
- **THE ACTUAL WORKER POOL**
- Manages pool of GleitzeitClient instances
- Each client is a complete execution unit
- Acquires/releases clients per request
- Initial size: max_size/2, grows to max_size as needed
- **Stateless pool management** - clients are interchangeable

#### **GleitzeitClient** (`src/gleitzeit/client/client.py`)
- **Each client instance acts as a worker**
- Complete execution environment with:
  - NativeAdapter with embedded ExecutionEngine
  - TaskExecutor for task execution
  - Provider connections (via hub or direct)
- Can process entire workflows independently
- **Stateless between requests** - no request-specific state retained

#### **API Routes** (`src/gleitzeit/api/routes/workflows.py`)
- Thin layer that delegates to client methods
- Uses dependency injection: `client: GleitzeitClient = Depends(get_client)`
- Each request gets a client from the pool
- Executes workflow through client, returns client to pool

### 3. Processing Model

**Current: Client Pool as Worker Pool**
```python
# API Route (workflows.py)
@router.post("/")
async def submit_workflow(
    request: WorkflowSubmissionRequest,
    client: GleitzeitClient = Depends(get_client)  # Gets client from pool
):
    workflow = Workflow(**request.workflow)
    # Client acts as worker - executes entire workflow
    return await client.submit_workflow(workflow)

# Client Pool (dependencies.py)
async def get_pooled_client():
    pool = await get_client_pool()  # Global pool of 10 clients
    client = await pool.acquire()    # Get available "worker"
    try:
        yield client
    finally:
        await pool.release(client)   # Return "worker" to pool
```

**How It Works:**
- **ClientPool = Worker Pool** (10 clients = 10 concurrent workers)
- Each client is a complete execution unit
- Clients are reused across requests
- Pool grows from initial_size to max_size as needed
- **Concurrent execution**: Multiple clients can process workflows simultaneously

### 4. Current Scaling Approach

#### **What Works Well:**
1. **Concurrent execution** - Pool of 10 clients = 10 concurrent workflows
2. **Resource reuse** - Clients are reused, avoiding initialization overhead
3. **Stateless clients** - Any client can handle any request
4. **Pool growth** - Dynamically grows from initial to max size

#### **Scaling Limitations:**
1. **Single machine limit** - All clients in same API process
2. **Fixed pool size** - Max 10 concurrent workflows per API instance
3. **Memory pressure** - Each client has full execution stack
4. **No geographic distribution** - Can't place workers near resources
5. **Shared fate** - API crash affects all "workers"

#### **Current Horizontal Scaling:**
```yaml
# Deploy multiple API instances
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-api
spec:
  replicas: 5  # 5 instances × 10 clients = 50 concurrent workflows
```

## Enhanced Worker Architecture for True Scaling

### Understanding Current "Workers"
The ClientPool already implements a form of worker pattern:
- Each GleitzeitClient is essentially a worker
- Pool manages worker lifecycle
- Workers are stateless and reusable

**Key Insight:** We don't need to create workers from scratch - we need to **decouple the ClientPool from the API process**.

### Option 1: Separate Worker Service Using Existing ClientPool

```python
class WorkerService:
    """
    Standalone service that runs a ClientPool as workers.
    Decoupled from API - pulls work from queue.
    """
    
    def __init__(self, pool_size: int = 20, queue_url: str = None):
        # Use existing ClientPool - just more of them!
        self.client_pool = ClientPool(max_size=pool_size, mode=ClientMode.NATIVE)
        self.queue_url = queue_url or os.environ.get("TASK_QUEUE_URL")
        self.running = False
        
    async def run(self):
        """Run multiple workers concurrently using client pool"""
        await self.client_pool.initialize()
        self.running = True
        
        # Start multiple worker tasks - one per client
        workers = []
        for i in range(self.client_pool.max_size):
            worker = asyncio.create_task(self.worker_loop(i))
            workers.append(worker)
        
        # Wait for all workers
        await asyncio.gather(*workers)
    
    async def worker_loop(self, worker_id: int):
        """Individual worker loop using pooled client"""
        while self.running:
            try:
                # Get workflow from queue
                workflow = await self.get_next_workflow()
                if not workflow:
                    await asyncio.sleep(1)
                    continue
                
                # Get client from pool (existing code!)
                client = await self.client_pool.acquire()
                try:
                    # Execute workflow using client
                    result = await client.submit_workflow(workflow)
                    await self.report_result(workflow.id, result)
                finally:
                    # Return client to pool
                    await self.client_pool.release(client)
                    
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")
```

### Option 2: Direct Scaling - Just Run More ClientPools

```python
# Simple approach: Run ClientPool as standalone service
async def run_worker_pool(size: int = 50):
    """
    Run a larger client pool as a worker service.
    No code changes needed!
    """
    # Create bigger pool
    worker_pool = ClientPool(max_size=size, mode=ClientMode.NATIVE)
    await worker_pool.initialize()
    
    # Expose via simple HTTP API
    app = FastAPI()
    
    @app.post("/execute")
    async def execute_workflow(workflow: Workflow):
        client = await worker_pool.acquire()
        try:
            return await client.submit_workflow(workflow)
        finally:
            await worker_pool.release(client)
    
    # Run service
    uvicorn.run(app, host="0.0.0.0", port=8091)
```

### Option 3: Distributed ClientPools with Load Balancer

```yaml
# Deploy multiple worker services
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: gleitzeit-workers
spec:
  replicas: 10  # 10 worker pods
  template:
    spec:
      containers:
      - name: worker
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.worker_service"]
        env:
        - name: POOL_SIZE
          value: "50"  # 50 clients per pod = 500 total workers
        - name: RESOURCE_SERVICE_URL
          value: "http://resource-service:8080"
---
apiVersion: v1
kind: Service
metadata:
  name: worker-pool
spec:
  selector:
    app: gleitzeit-workers
  ports:
  - port: 8091
  type: LoadBalancer
```

## Recommended Architecture: Leverage Existing ClientPool Pattern

### Key Insight
**We already have workers! Each GleitzeitClient in the pool IS a worker.**
- Don't reinvent - just decouple and scale
- ClientPool pattern already provides pooling, lifecycle, reuse
- Just need to run pools outside API process

### Recommended Architecture
```
┌─────────────────────────────────────────────────┐
│                   API Layer                       │
│         (Thin layer - routes requests)            │
│         ClientPool (small, for sync tasks)        │
└────────────────────┬─────────────────────────────┘
                     │
                Routes to
                     │
┌────────────────────▼─────────────────────────────┐
│           Worker Service Layer                    │
│         (Multiple ClientPool instances)           │
├───────────────────────────────────────────────────┤
│  Pod 1: ClientPool(50)  = 50 workers              │
│  Pod 2: ClientPool(50)  = 50 workers              │
│  Pod N: ClientPool(50)  = 50 workers              │
│                                                   │
│  Total: N pods × 50 = N×50 concurrent workflows   │
└────────────────────┬─────────────────────────────┘
                     │
              Each client uses
                     │
┌────────────────────▼─────────────────────────────┐
│             Resource Service                      │
│     (Manages Ollama, Docker, Shell, etc)          │
│          Using StatelessResourceClient            │
└───────────────────────────────────────────────────┘
```

### Implementation Plan

#### Phase 1: Extract Worker Service (Minimal Changes)
```python
# New file: src/gleitzeit/worker/service.py
from gleitzeit.api.dependencies import ClientPool
from gleitzeit.client import ClientMode

class WorkerService:
    """Standalone worker service using ClientPool"""
    
    def __init__(self, pool_size: int = 50):
        self.pool = ClientPool(max_size=pool_size, mode=ClientMode.NATIVE)
        self.app = FastAPI(title="Gleitzeit Worker Service")
        
        @self.app.post("/execute")
        async def execute_workflow(workflow: Workflow):
            """Execute workflow using pooled client"""
            client = await self.pool.acquire()
            try:
                return await client.submit_workflow(workflow)
            finally:
                await self.pool.release(client)
    
    async def run(self, port: int = 8091):
        await self.pool.initialize()
        uvicorn.run(self.app, host="0.0.0.0", port=port)

# Run with: python -m gleitzeit.worker.service
```

#### Phase 2: Update API to Route to Workers
```python
# Update API to optionally route to worker service
class WorkflowRouter:
    def __init__(self, worker_service_url: Optional[str] = None):
        self.worker_service_url = worker_service_url or os.environ.get("WORKER_SERVICE_URL")
    
    async def submit_workflow(self, workflow: Workflow, client: GleitzeitClient):
        if self.worker_service_url and workflow.is_large():
            # Route to worker service for large workflows
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.worker_service_url}/execute",
                    json=workflow.dict()
                ) as response:
                    return await response.json()
        else:
            # Use local client pool for small workflows
            return await client.submit_workflow(workflow)
```

#### Phase 3: Deploy Worker Services
```yaml
# Kubernetes deployment for worker services
apiVersion: apps/v1
kind: Deployment
metadata:
  name: gleitzeit-workers
spec:
  replicas: 5  # Start with 5 pods
  template:
    spec:
      containers:
      - name: worker
        image: gleitzeit:latest
        command: ["python", "-m", "gleitzeit.worker.service"]
        env:
        - name: POOL_SIZE
          value: "100"  # 100 clients per pod = 500 total
        - name: RESOURCE_SERVICE_URL
          value: "http://resource-service:8080"
        resources:
          requests:
            memory: "4Gi"
            cpu: "2"
          limits:
            memory: "8Gi"
            cpu: "4"
```

## How This Aligns with Stateless Architecture

### Current State is Already Stateless
- **ClientPool**: Stateless pool management
- **GleitzeitClient**: Stateless between requests
- **Persistence**: All state in Redis/DB
- **Resources**: Would use StatelessResourceClient

### Worker Service Maintains Statelessness
```python
# Each worker client would use stateless resources
class WorkerService:
    def __init__(self, resource_service_url: str):
        self.pool = ClientPool(max_size=50)
        # Inject stateless resource client into each client
        self.resource_client = StatelessResourceClient(resource_service_url)
    
    async def initialize_client(self, client: GleitzeitClient):
        # Configure client with stateless resource access
        client.set_resource_client(self.resource_client)
```

### Horizontal Scaling Benefits

1. **True Distribution**: Workers anywhere, not just API replicas
2. **Resource Locality**: Place workers near Ollama/Docker resources  
3. **Independent Scaling**: Scale workers separately from API
4. **Fault Isolation**: Worker pods fail independently
5. **Load Distribution**: Load balancer distributes across worker pools

## Summary

### Key Findings:
1. **Gleitzeit already has workers** - ClientPool contains worker-like clients
2. **API uses client methods** - Routes delegate to pooled clients
3. **Scaling limitation** - Workers tied to API process

### Recommended Approach:
1. **Extract ClientPool into standalone service** - Minimal code changes
2. **Deploy multiple worker services** - Each with large ClientPool
3. **Route from API to workers** - For large/async workflows
4. **Use StatelessResourceClient** - For true stateless operation

### Why This Works:
- **Leverages existing code** - ClientPool and GleitzeitClient unchanged
- **Maintains statelessness** - Clients already stateless
- **Simple to implement** - Just decouple and deploy
- **Easy to scale** - Just add more worker pods

The architecture is already 90% there - just needs to be decoupled from the API process!