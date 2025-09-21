# Unified Pathway Audit - Single Path Through SystemManager

## Context
References: [WORKFLOW-SUBMISSION-AUDIT.md](./WORKFLOW-SUBMISSION-AUDIT.md)

## Requirements
1. **API should be a thin layer** for client functions
2. **Support Python SDK usage** (using Gleitzeit from within Python files)
3. **Single pathway through SystemManager** for all workflow submissions
4. **Maintain native/API client split** for different use cases
5. **Unified SystemManager discovery** across all contexts
6. **Support horizontal scaling** with multiple API instances
7. **Work with connection pooling** for efficient resource usage

## Current Architecture Problems

### Problem 1: Dual Client Implementation
```
Native Client → Direct persistence/execution (BYPASSES SystemManager)
API Client → HTTP API → Multiple paths (worker/SystemManager/fallback)
```

### Problem 2: API Not Being Thin
The API currently has business logic (choosing between worker router, SystemManager, and client fallback).

### Problem 3: Python SDK Usage Unclear
When using Gleitzeit from Python, it's unclear which path to take.

### Problem 4: SystemManager Discovery Not Unified
- `get_system_manager()` only exists in API dependencies
- No unified way to discover SystemManager across contexts
- Native mode can't discover existing SystemManager

### Problem 5: Horizontal Scaling Issues
- Multiple API instances each create their own SystemManager
- No coordination between SystemManager instances
- Client pooling not integrated with SystemManager discovery

## Proposed Architecture

### Core Principle: SystemManager as Single Entry Point

```
┌─────────────────────────────────────────────────┐
│              All Entry Points                    │
├─────────────┬──────────────┬────────────────────┤
│   API       │   Python SDK │     CLI           │
│  (thin)     │   (native)   │   (uses SDK)      │
└──────┬──────┴──────┬───────┴────────────────────┘
       │             │
       ▼             ▼
┌──────────────────────────────────────────────────┐
│            GleitzeitClient                        │
│  ┌──────────────┐  ┌──────────────────────┐     │
│  │ API Adapter  │  │   Native Adapter      │     │
│  │ (remote)     │  │   (in-process)        │     │
│  └──────┬───────┘  └──────────┬───────────┘     │
└─────────┼──────────────────────┼─────────────────┘
          │                      │
          ▼                      ▼
    ┌──────────┐          ┌──────────────┐
    │   HTTP   │          │SystemManager │
    │   API    │          │  (direct)    │
    └─────┬────┘          └──────────────┘
          │                      ▲
          └──────────────────────┘
                    │
                    ▼
         ┌───────────────────┐
         │ WorkflowManager   │
         │ - Validation      │
         │ - Persistence     │
         │ - Execution       │
         └───────────────────┘
```

## Implementation Details

### 1. Native Client Adapter (for Python SDK/in-process usage)
```python
# src/gleitzeit/client/adapters/native.py
class NativeAdapter(BaseAdapter):
    """
    Native adapter for in-process Python SDK usage.
    Directly uses SystemManager (no HTTP overhead).
    """
    
    def __init__(self, system_manager=None):
        # If no system_manager provided, create/get the singleton
        self.system_manager = system_manager or get_system_manager()
        if not self.system_manager:
            raise RuntimeError("SystemManager is required for native adapter")
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow through SystemManager directly."""
        if not self.system_manager.workflow_manager:
            raise RuntimeError("WorkflowManager not initialized")
        
        # Direct call to SystemManager's WorkflowManager
        return await self.system_manager.workflow_manager.submit_workflow(workflow)
    
    async def get_workflow(self, workflow_id: str) -> Workflow:
        """Get workflow through SystemManager."""
        return await self.system_manager.workflow_manager.get_workflow(workflow_id)
    
    # Other methods follow same pattern...
```

### 2. API Client Adapter (for remote/distributed usage)
```python
# src/gleitzeit/client/adapters/api.py
class APIAdapter(BaseAdapter):
    """
    API adapter for remote usage.
    Uses HTTP to communicate with API server.
    """
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = aiohttp.ClientSession()
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow through HTTP API."""
        response = await self.session.post(
            f"{self.base_url}/api/workflows/",
            json=workflow.dict()
        )
        if response.status != 200:
            raise WorkflowSubmissionError(await response.text())
        
        data = await response.json()
        return data["workflow_id"]
    
    # Other methods follow same pattern...
```

### 3. Unified SystemManager Discovery (NEW)
```python
# src/gleitzeit/system/manager.py
"""
Unified SystemManager discovery for all contexts.
Supports horizontal scaling and connection pooling.
"""

import threading
from typing import Optional

# Global SystemManager instance (per-process singleton)
_system_manager_instance: Optional[SystemManager] = None
# Lock for thread-safe access in multi-threaded environments
_manager_lock = threading.Lock()

def get_system_manager() -> Optional[SystemManager]:
    """
    Get the global SystemManager instance.
    Thread-safe singleton access for all contexts.
    """
    return _system_manager_instance

def set_system_manager(manager: Optional[SystemManager]) -> None:
    """
    Set the global SystemManager instance.
    Used by the component that creates the SystemManager.
    """
    global _system_manager_instance
    with _manager_lock:
        _system_manager_instance = manager

async def discover_system_manager(persistence=None) -> Optional[SystemManager]:
    """
    Discover existing SystemManager from persistence or environment.
    Used for horizontal scaling - finds active SystemManager instances.
    """
    if persistence is None:
        from gleitzeit.persistence.factory import PersistenceFactory
        persistence = await PersistenceFactory.create()
    
    # Check if there's a local SystemManager first
    local_manager = get_system_manager()
    if local_manager:
        return local_manager
    
    # Try to discover from persistence (for distributed systems)
    # SystemManagers register themselves in Redis/persistence
    from gleitzeit.system.distributed_registry import DistributedRegistry
    registry = DistributedRegistry(persistence)
    
    # Find active SystemManager instances
    active_managers = await registry.get_active_system_managers()
    if active_managers:
        # For native mode, we can connect to any active SystemManager
        # They all share the same persistence backend
        return active_managers[0]  # Could implement load balancing here
    
    return None

async def ensure_system_manager(persistence=None, create_if_missing=True) -> SystemManager:
    """
    Get existing or create new SystemManager.
    Handles both single-instance and horizontally-scaled deployments.
    """
    # Try discovery first
    manager = await discover_system_manager(persistence)
    if manager:
        return manager
    
    if not create_if_missing:
        raise RuntimeError("No SystemManager available and creation disabled")
    
    # Create new SystemManager if none exists
    with _manager_lock:
        # Double-check after acquiring lock
        if _system_manager_instance:
            return _system_manager_instance
            
        # Create new instance
        if persistence is None:
            from gleitzeit.persistence.factory import PersistenceFactory
            persistence = await PersistenceFactory.create()
        
        manager = SystemManager(persistence=persistence)
        await manager.initialize()
        await manager.start_system()
        
        # Register globally and in distributed registry
        set_system_manager(manager)
        
        # Register in distributed registry for discovery by other instances
        from gleitzeit.system.distributed_registry import DistributedRegistry
        registry = DistributedRegistry(persistence)
        await registry.register_system_manager(manager)
        
        return manager
```

### 4. API as Thin Layer (no business logic)
```python
# src/gleitzeit/api/routes/workflows.py
@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(
    request: WorkflowSubmissionRequest,
    system_manager = Depends(get_system_manager)
):
    """
    Thin API layer - just forwards to SystemManager.
    No business logic, no fallbacks, no alternate paths.
    """
    if not system_manager:
        raise HTTPException(503, "Service unavailable")
    
    workflow = Workflow(**request.workflow)
    
    # Single path: API -> SystemManager
    try:
        workflow_id = await system_manager.workflow_manager.submit_workflow(workflow)
        return {"workflow_id": workflow_id, "status": "submitted"}
    except WorkflowValidationError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Internal error: {str(e)}")

# Remove worker router, remove client fallback, remove all alternate paths
```

### 4. Horizontal Scaling Support

#### Problem Statement
When running multiple API instances for horizontal scaling:
- Each instance needs to discover or create SystemManager
- SystemManagers must coordinate through shared persistence
- Connection pools must be aware of multiple instances
- Load balancing should distribute work effectively

#### Solution: Distributed Registry
```python
# src/gleitzeit/system/distributed_registry.py
class DistributedRegistry:
    """
    Registry for SystemManager instances in distributed deployments.
    Uses Redis/persistence for coordination between instances.
    """
    
    def __init__(self, persistence: PersistenceBackend):
        self.persistence = persistence
        self.ttl = 30  # seconds - heartbeat interval
    
    async def register_system_manager(self, manager: SystemManager) -> None:
        """
        Register a SystemManager instance in the distributed registry.
        Called on startup and periodically for heartbeat.
        """
        key = f"system_manager:{manager.instance_id}"
        value = {
            "instance_id": manager.instance_id,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "started_at": manager.started_at.isoformat(),
            "last_heartbeat": datetime.utcnow().isoformat(),
            "capabilities": {
                "workflow_execution": True,
                "event_processing": True,
                "stream_support": manager.stream_enabled
            }
        }
        await self.persistence.set(key, json.dumps(value), ttl=self.ttl)
    
    async def get_active_system_managers(self) -> List[Dict]:
        """
        Get all active SystemManager instances from the registry.
        Filters out expired entries based on heartbeat TTL.
        """
        pattern = "system_manager:*"
        keys = await self.persistence.keys(pattern)
        
        active_managers = []
        for key in keys:
            data = await self.persistence.get(key)
            if data:
                manager_info = json.loads(data)
                # Check if heartbeat is recent (within TTL window)
                last_heartbeat = datetime.fromisoformat(manager_info["last_heartbeat"])
                if (datetime.utcnow() - last_heartbeat).seconds < self.ttl * 2:
                    active_managers.append(manager_info)
        
        return active_managers
    
    async def select_manager_for_load_balancing(self) -> Optional[Dict]:
        """
        Select a SystemManager for handling a request using load balancing.
        Can implement various strategies: round-robin, least-loaded, etc.
        """
        managers = await self.get_active_system_managers()
        if not managers:
            return None
        
        # Simple round-robin for now
        # Could enhance with metrics-based selection
        import random
        return random.choice(managers)
```

### 5. Connection Pooling Integration

#### Unified Pool Across Instances
```python
# src/gleitzeit/api/shared_dependencies.py
class SharedClientPool:
    """
    Distributed client pool that coordinates across API instances.
    Uses Redis to track pool state and implement fair sharing.
    """
    
    def __init__(
        self,
        persistence: PersistenceBackend,
        instance_id: str,
        max_size: int = 20,  # Total across all instances
        mode: ClientMode = ClientMode.NATIVE,
        system_manager: Optional[SystemManager] = None
    ):
        self.persistence = persistence
        self.instance_id = instance_id
        self.max_size = max_size
        self.mode = mode
        self.system_manager = system_manager
        self.local_clients = []  # Local client cache
        self.pool_key = "client_pool:state"
        self.lock_key = "client_pool:lock"
    
    async def acquire(self) -> GleitzeitClient:
        """
        Acquire a client from the distributed pool.
        Implements fair sharing across instances.
        """
        # Try local cache first
        if self.local_clients:
            return self.local_clients.pop()
        
        # Acquire distributed lock for pool modification
        async with self.distributed_lock():
            pool_state = await self.get_pool_state()
            
            # Check if we can create a new client
            if pool_state["total_clients"] < self.max_size:
                client = await self.create_client()
                pool_state["total_clients"] += 1
                pool_state["instances"][self.instance_id]["count"] += 1
                await self.set_pool_state(pool_state)
                return client
            
            # Wait for available client or timeout
            return await self.wait_for_available_client()
    
    async def release(self, client: GleitzeitClient) -> None:
        """Release client back to the pool."""
        # Add to local cache for reuse
        self.local_clients.append(client)
        
        # Update distributed state
        async with self.distributed_lock():
            pool_state = await self.get_pool_state()
            pool_state["available_clients"] += 1
            await self.set_pool_state(pool_state)
    
    async def create_client(self) -> GleitzeitClient:
        """Create a new client connected to SystemManager."""
        if self.mode == ClientMode.NATIVE:
            # Use the unified SystemManager discovery
            from gleitzeit.system.manager import get_system_manager
            system_manager = self.system_manager or get_system_manager()
            
            from gleitzeit.client.adapters.native import NativeAdapter
            adapter = NativeAdapter(system_manager=system_manager)
        else:
            from gleitzeit.client.adapters.api import APIAdapter
            adapter = APIAdapter(base_url=self.base_url)
        
        client = GleitzeitClient(adapter=adapter)
        await client.initialize()
        return client
    
    @asynccontextmanager
    async def distributed_lock(self, timeout: int = 5):
        """Distributed lock for pool operations."""
        # Implement Redis-based distributed lock
        # This ensures only one instance modifies pool state at a time
        lock_acquired = False
        try:
            lock_acquired = await self.persistence.set_nx(
                self.lock_key, 
                self.instance_id, 
                ttl=timeout
            )
            if not lock_acquired:
                # Wait and retry
                await asyncio.sleep(0.1)
                lock_acquired = await self.persistence.set_nx(
                    self.lock_key, 
                    self.instance_id, 
                    ttl=timeout
                )
            yield
        finally:
            if lock_acquired:
                await self.persistence.delete(self.lock_key)
```

### 6. Client Factory Pattern (Updated for Unified Discovery)
```python
# src/gleitzeit/client/client.py
class GleitzeitClient:
    """
    Unified client that can work in both native and API modes.
    """
    
    @classmethod
    async def create(cls, mode: str = "auto", **kwargs):
        """
        Factory method to create appropriate client.
        Now uses unified SystemManager discovery.
        
        Args:
            mode: "native" | "api" | "auto"
            **kwargs: Additional arguments for adapter
        
        Returns:
            GleitzeitClient with appropriate adapter
        """
        if mode == "auto":
            # Use unified discovery from system.manager module
            from gleitzeit.system.manager import discover_system_manager
            
            # Try to discover existing SystemManager
            system_manager = await discover_system_manager()
            if system_manager:
                mode = "native"
                kwargs["system_manager"] = system_manager
            else:
                mode = "api"
        
        if mode == "native":
            from .adapters.native import NativeAdapter
            # Ensure SystemManager is available for native mode
            if "system_manager" not in kwargs:
                from gleitzeit.system.manager import ensure_system_manager
                kwargs["system_manager"] = await ensure_system_manager()
            adapter = NativeAdapter(**kwargs)
        elif mode == "api":
            from .adapters.api import APIAdapter
            if "base_url" not in kwargs:
                kwargs["base_url"] = os.getenv("GLEITZEIT_API_URL", "http://localhost:8080")
            adapter = APIAdapter(**kwargs)
        else:
            raise ValueError(f"Unknown mode: {mode}")
        
        return cls(adapter=adapter)
    
    def __init__(self, adapter):
        self.adapter = adapter
    
    async def submit_workflow(self, workflow: Workflow) -> str:
        """Submit workflow through configured adapter."""
        return await self.adapter.submit_workflow(workflow)
```

### 7. API Dependencies Update (Use Unified Discovery)
```python
# src/gleitzeit/api/dependencies.py
async def get_system_manager():
    """
    Get the shared SystemManager instance.
    Now uses unified discovery from system.manager module.
    """
    # Import unified discovery functions
    from gleitzeit.system.manager import get_system_manager as get_global_manager
    from gleitzeit.system.manager import ensure_system_manager
    
    # Try to get existing SystemManager first
    manager = get_global_manager()
    if manager:
        return manager
    
    # If none exists, ensure one is created
    # This handles both single-instance and horizontally-scaled deployments
    manager = await ensure_system_manager()
    return manager

async def get_shared_client_pool(request: Optional[Request] = None):
    """
    Get or create the shared client pool instance.
    Uses unified SystemManager discovery.
    """
    global _shared_client_pool
    
    if _shared_client_pool is None:
        from gleitzeit.api.shared_dependencies import SharedClientPool
        from gleitzeit.system.manager import ensure_system_manager
        import os
        
        # Get persistence backend
        persistence = await PersistenceFactory.create()
        
        # Use unified SystemManager discovery
        system_manager = await ensure_system_manager(persistence)
        
        # Create connection to shared pool
        instance_id = f"api_{socket.gethostname()}_{os.getpid()}"
        
        _shared_client_pool = SharedClientPool(
            persistence=persistence,
            instance_id=instance_id,
            max_size=20,  # Total across all API instances
            mode=ClientMode.NATIVE,
            system_manager=system_manager  # Use discovered/created SystemManager
        )
        await _shared_client_pool.initialize()
    
    return _shared_client_pool
```

### 8. Python SDK Usage Examples

#### Example 1: In-Process Usage (Native)
```python
# my_script.py
from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task

async def main():
    # Native client - runs in same process, no HTTP
    client = GleitzeitClient.create(mode="native")
    
    workflow = Workflow(
        id="my-workflow",
        tasks=[...]
    )
    
    # Goes directly through SystemManager
    workflow_id = await client.submit_workflow(workflow)
```

#### Example 2: Remote Usage (API)
```python
# remote_script.py
from gleitzeit.client import GleitzeitClient

async def main():
    # API client - uses HTTP to remote server
    client = GleitzeitClient.create(
        mode="api",
        base_url="http://gleitzeit-server:8080"
    )
    
    # Goes through HTTP API -> SystemManager
    workflow_id = await client.submit_workflow(workflow)
```

#### Example 3: Auto-Detection
```python
# flexible_script.py
from gleitzeit.client import GleitzeitClient

async def main():
    # Auto mode - detects if running in-process or needs API
    client = GleitzeitClient.create(mode="auto")
    
    # Automatically uses best path
    workflow_id = await client.submit_workflow(workflow)
```

### 6. CLI Usage
```python
# src/gleitzeit/cli/commands/workflow.py
@workflow.command()
async def submit(workflow_file: str, mode: str = "auto"):
    """Submit workflow through unified pathway."""
    
    # CLI uses the same client factory
    client = GleitzeitClient.create(mode=mode)
    
    with open(workflow_file) as f:
        workflow = Workflow.parse(f.read())
    
    workflow_id = await client.submit_workflow(workflow)
    print(f"Submitted: {workflow_id}")
```

## Horizontal Scaling Scenarios

### Scenario 1: Multiple API Instances
```
┌────────────┐  ┌────────────┐  ┌────────────┐
│   API-1    │  │   API-2    │  │   API-3    │
│  (port 8001)│  │  (port 8002)│  │  (port 8003)│
└─────┬──────┘  └─────┬──────┘  └─────┬──────┘
      │                │                │
      └────────────────┴────────────────┘
                       │
                ┌──────▼──────┐
                │    Redis    │
                │ (shared     │
                │  registry)  │
                └─────────────┘
```

Each API instance:
1. Creates its own SystemManager on startup
2. Registers in distributed registry via Redis
3. Shares connection pool state via Redis
4. Can discover other SystemManager instances

### Scenario 2: Python SDK Discovery
```python
# Python script using SDK
async def main():
    # Client discovers SystemManager automatically
    client = await GleitzeitClient.create(mode="auto")
    
    # Discovery process:
    # 1. Check local get_system_manager() - returns None if not in API process
    # 2. Call discover_system_manager() - finds active instances via Redis
    # 3. If found, use native mode with discovered SystemManager
    # 4. If not found, fall back to API mode
    
    workflow_id = await client.submit_workflow(workflow)
```

### Scenario 3: Load Balancing
```python
# Multiple SystemManagers registered
managers = [
    {"instance_id": "api_host1_1234", "load": 10},
    {"instance_id": "api_host2_5678", "load": 5},
    {"instance_id": "api_host3_9012", "load": 15}
]

# Load balancer selects least loaded
selected = min(managers, key=lambda m: m["load"])
# Returns api_host2_5678
```

## Benefits of This Architecture

### 1. Single Pathway Guarantee
- **Native mode**: Client → SystemManager → WorkflowManager
- **API mode**: Client → HTTP → API → SystemManager → WorkflowManager
- **No bypasses possible**

### 2. API as Thin Layer
- API just forwards to SystemManager
- No business logic in API
- Easy to maintain and test

### 3. Flexible Usage
- Python scripts can use native mode (no HTTP overhead)
- Distributed systems can use API mode
- Auto-detection for convenience

### 4. Clear Separation
- **Client**: Interface and adapter selection
- **API**: Thin HTTP layer
- **SystemManager**: Single entry point for all operations
- **WorkflowManager**: Business logic and validation

## Migration Path

### Phase 1: Update Native Adapter
1. Modify NativeAdapter to use SystemManager
2. Remove direct persistence access
3. Remove local execution logic

### Phase 2: Simplify API
1. Remove worker router path
2. Remove client fallback
3. Make API a pure forwarding layer

### Phase 3: Client Factory
1. Implement factory pattern
2. Add auto-detection logic
3. Update documentation

### Phase 4: Update CLI
1. Use client factory
2. Add mode selection option
3. Test all paths

## Testing Strategy

### Test Matrix
| Entry Point | Adapter | Path | Expected Result |
|------------|---------|------|-----------------|
| Python SDK | Native | Direct SystemManager | ✓ Validation at submission |
| Python SDK | API | HTTP → SystemManager | ✓ Validation at submission |
| CLI | Native | Direct SystemManager | ✓ Validation at submission |
| CLI | API | HTTP → SystemManager | ✓ Validation at submission |
| HTTP API | - | SystemManager | ✓ Validation at submission |

### Test Cases
1. **Valid workflow** → Accepted at submission
2. **Invalid method** → Rejected at submission (not execution)
3. **Missing SystemManager** → Native fails, API works if server running
4. **Auto-detection** → Correct adapter selected

## Summary

This architecture achieves:
1. ✅ **Single pathway through SystemManager** - all paths converge
2. ✅ **API as thin layer** - no business logic, just forwarding
3. ✅ **Python SDK support** - native mode for in-process usage
4. ✅ **Flexibility** - different adapters for different use cases
5. ✅ **Clear separation** - each component has single responsibility
6. ✅ **Unified SystemManager discovery** - single mechanism for all contexts
7. ✅ **Horizontal scaling support** - multiple instances coordinate via Redis
8. ✅ **Connection pooling integration** - distributed pool management

The key insights:
- The native/API split is about **transport** (in-process vs HTTP), not about **logic paths**
- Both paths ultimately go through the same SystemManager → WorkflowManager pathway
- SystemManager discovery is unified across all contexts via `system.manager` module
- Horizontal scaling works through distributed registry in Redis
- Connection pools coordinate across instances for efficient resource usage
- Thread-safe singleton pattern ensures proper multi-threaded access

This ensures consistent validation at submission time (not execution time) and provides a single, unified pathway for all workflow submissions regardless of entry point.