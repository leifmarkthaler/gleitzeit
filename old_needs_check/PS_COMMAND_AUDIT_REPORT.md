# Gleitzeit PS Command Audit Report

## Executive Summary
The `gleitzeit ps` command is not properly displaying all running services. While services are correctly registered in Redis, the command has several issues that prevent proper display of both native and Docker services.

## Current State

### What's Working
1. **Native services (API, UI) are registering in Redis**
   - Keys: `service:registry:api` and `service:registry:ui`
   - Registration includes: pid, port, host, started_at, mode

2. **Docker workers are registering in Redis**
   - Keys: `{shard:0}:worker:registry:{type}:{id}`
   - 8 Docker workers successfully registered (task_execution, workflow_loader, etc.)
   - Workers use different registry pattern due to sharding

3. **Redis URL configuration is now properly managed**
   - Fixed hardcoded `redis://localhost:6379` references
   - Now uses ConfigurationManager.get_redis_url() throughout

### Issues Identified

#### Issue 1: Service Staleness Threshold Too Aggressive
**Problem**: Services are marked as "stale" after only 5 minutes
- Line 73 in ps_command.py: `is_healthy = time_since_start < timedelta(minutes=5)`
- This causes legitimate long-running services to be hidden unless `--all` flag is used

**Impact**: Users can't see healthy services that have been running for more than 5 minutes

#### Issue 2: Workers Not Displayed in PS Command
**Problem**: The ps command only looks for `service:registry:*` keys, missing worker registrations
- Workers register under `{shard:0}:worker:registry:*` pattern
- ps command doesn't scan for worker registry keys

**Impact**: Docker workers are completely invisible in ps output

#### Issue 3: No Service Registration Refresh
**Problem**: Services only register once at startup
- API/UI services register via FastAPI lifespan but never update
- No heartbeat or TTL refresh mechanism for service entries
- Workers have heartbeat (line 306 in base.py) but services don't

**Impact**: Long-running services appear stale even though they're healthy

#### Issue 4: Worker Registry Has Inconsistent Data
**Problem**: Worker registry entries have different fields than service registry
- Workers have: worker_type, worker_id, shards, started_at, status, host, pid
- Services have: pid, port, host, started_at, mode
- No "mode" field for workers to indicate Docker vs native

**Impact**: Difficult to unify display of services and workers

## Root Cause Analysis

### Registration Flow
1. **Native Services (API/UI)**:
   - Register via `SmartProcessManager.register_service()`
   - Store in `service:registry:{service_type}`
   - No refresh mechanism after initial registration

2. **Docker Workers**:
   - Register via `BaseWorker._register_worker()`
   - Store in `{shard:0}:worker:registry:{type}:{id}`
   - Have heartbeat that refreshes registration with 60s TTL

### Key Design Issues
1. **Two separate registry systems**: Services vs Workers
2. **Inconsistent TTL management**: Workers have TTL, services don't
3. **Hardcoded staleness threshold**: 5 minutes is too short for production
4. **Missing unification layer**: No abstraction to handle both registry types

## Recommendations

### Immediate Fixes
1. **Increase staleness threshold** to 30-60 minutes or make it configurable
2. **Add worker scanning** to ps command to include worker registry entries
3. **Add service heartbeat** similar to worker heartbeat with TTL refresh

### Long-term Improvements
1. **Unify registry format** - standardize fields across services and workers
2. **Add "last_seen" timestamp** that gets updated on heartbeat
3. **Make staleness configurable** via environment variable or config
4. **Add health check endpoint** for services to report status

## Files Requiring Changes

1. **src/gleitzeit/cli/ps_command.py**
   - Line 73: Increase staleness threshold
   - Line 55: Add scanning for worker registry keys
   - Add worker display logic

2. **src/gleitzeit/ui/api/app.py** and **src/gleitzeit/ui/app.py**
   - Add periodic registration refresh task
   - Update registration on heartbeat interval

3. **src/gleitzeit/core/process_manager.py**
   - Add service heartbeat mechanism
   - Set TTL on service registry entries

4. **src/gleitzeit/workers/base.py**
   - Already has good heartbeat pattern - can be used as reference

## Testing Recommendations

1. Start native API/UI services
2. Start Docker workers
3. Wait > 5 minutes
4. Run `gleitzeit ps` - should show all services as healthy
5. Run `gleitzeit ps --all` - should show both services and workers
6. Stop a service and verify it disappears from ps output after TTL expires

## Conclusion

The ps command infrastructure is mostly in place but needs key improvements:
- Extend staleness threshold from 5 minutes to 30+ minutes
- Include worker registry entries in ps output
- Add heartbeat/TTL refresh for service registrations
- Unify the display format for services and workers

These changes will make `gleitzeit ps` a reliable tool for monitoring both native and Docker deployments in a horizontally scaled environment.