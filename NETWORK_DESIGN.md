# Design Draft: Multi-Instance Network Strategy

## Current Situation

**Problem 1:** Original implementation used a single shared network name `gleitzeit_network` for all instances
- ❌ Docker Compose fails when network exists but wasn't created by Compose
- ❌ Conflicts with existing monitoring stack using the same network

**Problem 2:** Initial fix used instance-specific networks `gleitzeit_network_{instance_id}`
- ✅ No conflicts
- ❌ **Instances can't share workers** - each instance is isolated
- ❌ Breaks horizontal scaling use cases

## Requirements

1. **Multiple instances must share workers** when using the same Redis
2. **No network conflicts** with existing networks (like monitoring stack)
3. **Support both shared and isolated deployments**
4. **Container names must be unique** (no conflicts between instances)
5. **Backward compatible** with existing monitoring infrastructure

## Proposed Design Options

### Option A: Always Use Shared Network (Simplest)

**Strategy:** All Gleitzeit instances share `gleitzeit_network`, mark it as `external: true`

```yaml
networks:
  gleitzeit:
    name: gleitzeit_network
    external: true  # Don't try to create/manage it
```

**Implementation:**
1. Check if `gleitzeit_network` exists
2. If not, create it once: `docker network create gleitzeit_network`
3. All instances use `external: true` to reference it
4. Container names remain instance-specific: `gleitzeit_api_{instance_id}`

**Pros:**
- ✅ Simple and predictable
- ✅ All instances can share workers
- ✅ No conflicts (external: true prevents Compose from trying to manage it)
- ✅ Works with existing monitoring stack

**Cons:**
- ❌ Can't run truly isolated instances (but is this needed?)
- ❌ All instances must trust the same network

**Use Cases:**
- ✅ Scale API: `gleitzeit serve --api-only` (multiple times)
- ✅ Scale workers: `gleitzeit serve --workers-only` (multiple times)
- ✅ Full stack: `gleitzeit serve` (coexists with monitoring)

---

### Option B: Smart Network Selection (More Flexible)

**Strategy:** Choose network based on deployment mode

```python
if using_same_redis_as_existing_instance():
    network = "gleitzeit_network"  # Shared
    external = True
else:
    network = f"gleitzeit_network_{instance_id}"  # Isolated
    external = False
```

**Detection Logic:**
1. Check if other Gleitzeit containers are running on `gleitzeit_network`
2. If yes → join the shared network
3. If no → create new isolated network

**Pros:**
- ✅ Automatic clustering when needed
- ✅ Automatic isolation when appropriate
- ✅ Most flexible

**Cons:**
- ❌ Complex logic
- ❌ Harder to predict behavior
- ❌ Race conditions if multiple instances start simultaneously

---

### Option C: Explicit Mode Flag (User Control)

**Strategy:** Add a flag to control network behavior

```bash
# Shared mode (default) - join gleitzeit_network
gleitzeit serve --shared

# Isolated mode - create instance-specific network
gleitzeit serve --isolated
```

**Implementation:**
```python
if isolated_mode:
    network = f"gleitzeit_network_{instance_id}"
    external = False
else:
    network = "gleitzeit_network"
    external = True
```

**Pros:**
- ✅ Explicit and predictable
- ✅ User has full control
- ✅ Supports both use cases

**Cons:**
- ❌ Requires user to understand the concept
- ❌ Extra flag to remember

---

### Option D: Network Based on Redis Configuration (Smart Default)

**Strategy:** Network sharing follows Redis sharing

```python
redis_host = get_redis_host(config)

if redis_host in ["localhost", "127.0.0.1", "redis"]:
    # Using container/local Redis → likely isolated deployment
    network = f"gleitzeit_network_{instance_id}"
    external = False
else:
    # Using external Redis → likely shared deployment
    network = "gleitzeit_network"
    external = True
```

**Pros:**
- ✅ Intuitive: shared Redis → shared network
- ✅ No extra flags needed
- ✅ Handles most use cases automatically

**Cons:**
- ❌ Still can't share workers with local Redis
- ❌ Assumption might not always be correct

---

## Recommendation: **Option A** (Always Use Shared Network)

**Rationale:**
1. Gleitzeit is designed for **horizontal scaling** - sharing workers is a core feature
2. Network isolation at the Docker level is less important than Redis isolation
3. True multi-tenancy should use **separate Redis instances**, not separate networks
4. Simpler is better - one less thing to configure

### Implementation Plan

1. **Network Configuration:**
   - Always use `gleitzeit_network` with `external: true`
   - Create network on first run if it doesn't exist
   - All instances share this network

2. **Container Isolation:**
   - Keep instance-specific container names: `gleitzeit_api_{instance_id}`
   - Keep instance-specific volumes: `gleitzeit_logs_{instance_id}`
   - Prevents conflicts while allowing network sharing

3. **Backward Compatibility:**
   - Existing monitoring stack on `gleitzeit_network` works fine
   - New instances join the same network
   - No disruption to running services

### Code Changes Required

**In `generate_compose_file()` method:**

```python
# Use shared network for all instances
network_name = "gleitzeit_network"

compose = {
    "version": "3.8",
    "networks": {
        "gleitzeit": {
            "name": network_name,
            "external": True  # Use existing network, don't manage it
        }
    },
    "volumes": {
        "redis-data": {"name": f"gleitzeit_redis_data_{self.instance_id}"},
        "logs": {"name": f"gleitzeit_logs_{self.instance_id}"}
    },
    "services": {}
}

# Ensure the shared network exists
result = subprocess.run(
    ["docker", "network", "inspect", network_name],
    capture_output=True,
    text=True
)
if result.returncode != 0:
    # Network doesn't exist, create it
    click.echo(f"📡 Creating shared network '{network_name}'...")
    subprocess.run(
        ["docker", "network", "create", network_name],
        capture_output=True,
        text=True
    )
```

**Container names remain instance-specific** (already implemented):
- `gleitzeit_api_{instance_id}`
- `gleitzeit_ui_{instance_id}`
- `gleitzeit_worker-{type}-{n}_{instance_id}`

### Example Deployment Scenarios

#### Scenario 1: Single Full Stack
```bash
gleitzeit serve
```
- Creates/joins `gleitzeit_network`
- Starts API, UI, all workers
- Instance ID: `abc123`
- Containers: `gleitzeit_api_abc123`, `gleitzeit_ui_abc123`, etc.

#### Scenario 2: Scale Workers Horizontally
```bash
# Terminal 1: Main instance
gleitzeit serve

# Terminal 2: Additional workers
gleitzeit serve --workers-only
```
- Both join `gleitzeit_network`
- Both connect to same Redis
- Workers from both instances process jobs
- No container name conflicts

#### Scenario 3: Scale API Horizontally
```bash
# Terminal 1: API + workers
gleitzeit serve --api-port 8000

# Terminal 2: Additional API
gleitzeit serve --api-only --api-port 8001
```
- Both APIs share the same worker pool
- Load balancer can distribute across ports 8000 and 8001

#### Scenario 4: Coexist with Monitoring
```bash
# Monitoring stack already using gleitzeit_network
# Grafana, Prometheus, Loki running

gleitzeit serve
```
- Joins existing `gleitzeit_network` (external: true)
- No conflicts
- Can communicate with monitoring services

### Migration Path

**For users with existing deployments:**
1. Stop all Gleitzeit instances
2. Update to new version
3. Start instances - will automatically use `external: true`
4. Existing `gleitzeit_network` is reused
5. No manual network cleanup needed

### Future Enhancements (Optional)

If isolation is needed in the future, add `--isolated` flag:
```bash
gleitzeit serve --isolated
```
- Creates `gleitzeit_network_{instance_id}`
- Completely isolated deployment
- Opt-in feature for special cases

## Decision Required

Should we proceed with **Option A** (Always Use Shared Network)?

Alternative: Implement **Option C** (Option A + optional `--isolated` flag)?
