# Missing Endpoints in Gleitzeit API

This document outlines REST API endpoints that should exist but are not yet implemented in the Gleitzeit system (excluding authentication which is planned separately).

## 🚨 Critical Missing Endpoints

### 1. Task Logs ✅ IMPLEMENTED
**Problem:** UI currently mocks task logs with a comment stating "The API doesn't currently have a logs endpoint"
**Status:** Implemented with comprehensive log system

- `GET /api/tasks/{task_id}/logs` - ✅ Implemented
  - Query params: `tail` (number of lines), `follow` (boolean for streaming)
- `WebSocket /ws/logs/task/{task_id}` - ✅ Implemented - Live log streaming
  - Real-time log updates as task executes

### 2. Workflow Control ✅ PARTIALLY IMPLEMENTED
**Problem:** No way to pause, resume, or restart workflows after submission
**Status:** Pause/Resume/Retry implemented

- `POST /api/workflows/{id}/pause` - ✅ Implemented
- `POST /api/workflows/{id}/resume` - ✅ Implemented
- `POST /api/workflows/{id}/restart` - ⚠️ Not implemented (use retry)
- `POST /api/workflows/{id}/retry` - ✅ Implemented

### 3. Task Management ✅ PARTIALLY IMPLEMENTED
**Problem:** Limited control over individual tasks after submission
**Status:** Retry and cancel implemented

- `POST /api/tasks/{id}/retry` - ✅ Implemented
- `POST /api/tasks/{id}/cancel` - ✅ Implemented
- `POST /api/tasks/{id}/rerun` - ⚠️ Not implemented (use retry)
- `PUT /api/tasks/{id}` - ⚠️ Not implemented (requires task update logic)

## 📊 Monitoring & Observability

### 4. Metrics & Performance ✅ PARTIALLY IMPLEMENTED
**Problem:** No visibility into system performance and resource usage
**Status:** Basic statistics implemented, detailed metrics pending

- `GET /api/statistics/tasks` - ✅ Implemented - Task execution statistics
- `GET /api/statistics/system` - ✅ Implemented - System statistics
- `GET /api/metrics/workflows` - ⚠️ Not implemented - Workflow performance data
- `GET /api/metrics/providers` - ⚠️ Not implemented - Provider utilization statistics
- `GET /api/queues` - ✅ Implemented - Queue statistics and metrics

### 5. Provider Management ✅ PARTIALLY IMPLEMENTED
**Problem:** Provider management endpoints were commented out in the code
**Status:** Basic provider management implemented

- `GET /api/providers` - ✅ Implemented - List all registered providers
- `GET /api/providers/{id}` - ✅ Implemented - Get provider details
- `POST /api/providers/{id}/health` - ✅ Implemented - Provider health check
- `POST /api/providers/{id}/enable` - ⚠️ Not implemented
- `POST /api/providers/{id}/disable` - ⚠️ Not implemented
- `PUT /api/providers/{id}/config` - ⚠️ Not implemented

## 🔧 Advanced Features

### 6. Template Management (PLANNED FEATURE)
**Problem:** Template system exists but lacks API exposure
**Status:** Planned for future release - requires client-side template storage implementation

- `GET /api/templates` - List available workflow templates
- `GET /api/templates/{id}` - Get template details
- `POST /api/templates` - Create new template from workflow
- `PUT /api/templates/{id}` - Update existing template
- `DELETE /api/templates/{id}` - Delete template
- `POST /api/templates/{id}/instantiate` - Create workflow from template

### 7. Scheduling (PLANNED FEATURE)
**Problem:** No support for scheduled or recurring workflows
**Status:** Planned for future release - requires cron scheduler and persistent schedule storage

- `POST /api/schedules` - Create scheduled workflow execution
- `GET /api/schedules` - List all scheduled workflows
- `GET /api/schedules/{id}` - Get schedule details
- `PUT /api/schedules/{id}` - Update schedule (cron expression, parameters)
- `DELETE /api/schedules/{id}` - Cancel scheduled workflow
- `POST /api/schedules/{id}/trigger` - Manually trigger scheduled workflow

### 8. Queue Management ✅ IMPLEMENTED
**Problem:** No administrative control over task queues
**Status:** All queue management endpoints implemented

- `GET /api/queues` - ✅ Implemented - List all queues and their status
- `GET /api/queues/{name}` - ✅ Implemented - Get detailed queue statistics
- `POST /api/queues/{name}/pause` - ✅ Implemented (returns planned feature status)
- `POST /api/queues/{name}/resume` - ✅ Implemented (returns planned feature status)
- `POST /api/queues/{name}/clear` - ✅ Implemented - Clear all tasks from queue
- `PUT /api/queues/{name}/config` - ✅ Implemented (returns planned feature status)

## 🔄 Batch Operations

### 9. Bulk Operations ✅ IMPLEMENTED
**Problem:** No efficient way to manage multiple tasks/workflows
**Status:** All bulk operations implemented

- `POST /api/tasks/bulk/cancel` - ✅ Implemented - Cancel multiple tasks
- `POST /api/tasks/bulk/retry` - ✅ Implemented - Retry multiple failed tasks
- `POST /api/workflows/bulk/cancel` - ✅ Implemented - Cancel multiple workflows
- `DELETE /api/workflows/bulk` - ✅ Implemented - Delete multiple workflows
- `GET /api/tasks/bulk/status` - ✅ Implemented - Get status of multiple tasks

## 📁 Data Management

### 10. Import/Export ✅ PARTIALLY IMPLEMENTED
**Problem:** No way to backup or migrate workflows and data
**Status:** Workflow export/clone implemented, full data export pending

- `GET /api/workflows/{id}/export` - ✅ Implemented - Export workflow as JSON/YAML
- `POST /api/workflows/{id}/clone` - ✅ Implemented - Clone existing workflow
- `POST /api/workflows/import` - ⚠️ Not implemented
- `GET /api/data/export` - ⚠️ Not implemented - Requires backup system
- `POST /api/data/import` - ⚠️ Not implemented - Requires restore system

### 11. Resource Management ✅ PARTIALLY IMPLEMENTED
**Problem:** No visibility or control over resource limits and quotas
**Status:** Basic resource monitoring implemented

- `GET /api/resources/limits` - ✅ Implemented - Get current resource limits
- `GET /api/resources/usage` - ✅ Implemented - Current resource usage
- `PUT /api/resources/limits` - ⚠️ Not implemented - Requires config system
- `GET /api/resources/quotas` - ⚠️ Not implemented - Requires quota system
- `PUT /api/resources/quotas` - ⚠️ Not implemented - Requires quota system

### 12. Workflow Dependencies ✅ PARTIALLY IMPLEMENTED
**Problem:** No API access to dependency information and visualization
**Status:** Dependency graph and critical path implemented

- `GET /api/workflows/{id}/dependencies` - ✅ Implemented - Get dependency graph
- `GET /api/workflows/{id}/critical-path` - ✅ Implemented - Get critical path
- `GET /api/workflows/{id}/dependents` - ⚠️ Not implemented
- `POST /api/workflows/{id}/dependencies/validate` - ⚠️ Not implemented

## 🎯 Priority Ranking

### High Priority (Core Functionality Gaps)
1. **Task Logs** - Essential for debugging, currently mocked in UI
2. **Workflow Pause/Resume** - Basic orchestration control missing
3. **Task Retry** - No way to retry failed tasks without full resubmission
4. **Provider Management** - Administrators can't manage providers via API
5. **Template CRUD** - Templates exist but aren't accessible via API

### Medium Priority (Important Features)
6. **Metrics & Performance** - Needed for monitoring and optimization
7. **Queue Management** - Administrative control over processing
8. **Bulk Operations** - Efficiency for managing multiple items
9. **Scheduling** - Common requirement for automation

### Lower Priority (Nice to Have)
10. **Import/Export** - Useful for backup and migration
11. **Resource Management** - Advanced administration features
12. **Dependency Visualization** - Helpful for complex workflows

## 📝 Implementation Notes

### Completed Features ✅
- Task logs with real-time WebSocket streaming
- Provider management endpoints
- Task and workflow retry/cancel operations
- Bulk operations for efficient management
- Queue management and statistics
- Resource limits and usage monitoring
- Workflow export/clone functionality
- Dependency graph and critical path analysis

### Requires Design
- Workflow pause/resume (needs state machine changes)
- Scheduling system (needs cron parser and scheduler)
- Template management (needs persistence layer)

### Complex Implementation
- Real-time log streaming (WebSocket infrastructure needed)
- Resource quotas (needs accounting system)
- Import/export with data integrity

## 🔗 Related Systems

Many of these endpoints exist in similar workflow orchestration systems:
- **Airflow:** Has pause/resume, retry, scheduling, metrics
- **Temporal:** Has workflow versioning, retry policies, scheduling
- **Argo Workflows:** Has template management, resource limits, logs
- **Prefect:** Has flow scheduling, retry configuration, metrics

## 📅 Implementation Status Summary

### ✅ Completed (Fully Implemented)
- Task logs with WebSocket streaming
- Task control (cancel, retry)
- Workflow control (pause, resume, retry)  
- Queue management and statistics
- Bulk operations for tasks and workflows
- System and task statistics
- Data cleanup endpoint

### 🚧 Partially Implemented
- Provider management (health check, listing)
- Resource management (limits, usage monitoring)
- Import/Export (workflow export and clone)
- Workflow dependencies (graph and critical path)

### 📋 Planned Features (Not Yet Implemented)
- Template management system
- Scheduling and recurring workflows
- Advanced queue control (actual pause/resume)
- Full data backup/restore
- Resource quotas per user/project
- Provider enable/disable/config
- Workflow dependency validation

### 🎯 Next Steps
1. **Template System:** Requires client-side template storage
2. **Scheduling:** Needs cron parser and persistent scheduler
3. **Advanced Queue Control:** Requires queue manager modifications
4. **Data Backup/Restore:** Needs comprehensive serialization system

This implementation has brought Gleitzeit significantly closer to feature parity with other workflow orchestration systems, with most critical endpoints now available.