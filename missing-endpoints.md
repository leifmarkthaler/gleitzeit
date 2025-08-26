# Missing Endpoints in Gleitzeit API

This document outlines REST API endpoints that should exist but are not yet implemented in the Gleitzeit system (excluding authentication which is planned separately).

## 🚨 Critical Missing Endpoints

### 1. Task Logs
**Problem:** UI currently mocks task logs with a comment stating "The API doesn't currently have a logs endpoint"

- `GET /api/tasks/{task_id}/logs` - Retrieve task execution logs
  - Query params: `tail` (number of lines), `follow` (boolean for streaming)
- `WebSocket /api/tasks/{task_id}/logs/stream` - Live log streaming
  - Real-time log updates as task executes

### 2. Workflow Control
**Problem:** No way to pause, resume, or restart workflows after submission

- `POST /api/workflows/{id}/pause` - Pause a running workflow
- `POST /api/workflows/{id}/resume` - Resume a paused workflow  
- `POST /api/workflows/{id}/restart` - Restart a failed workflow from beginning
- `POST /api/workflows/{id}/retry` - Retry only failed tasks in workflow

### 3. Task Management
**Problem:** Limited control over individual tasks after submission

- `POST /api/tasks/{id}/retry` - Retry a failed task
- `POST /api/tasks/{id}/rerun` - Force rerun of a completed task
- `PUT /api/tasks/{id}` - Update task parameters/priority while queued

## 📊 Monitoring & Observability

### 4. Metrics & Performance
**Problem:** No visibility into system performance and resource usage

- `GET /api/metrics/tasks` - Task execution metrics
  - Average execution time, success rate, failure reasons
- `GET /api/metrics/workflows` - Workflow performance data
  - Completion time, throughput, bottlenecks
- `GET /api/metrics/providers` - Provider utilization statistics
  - Load distribution, response times, error rates
- `GET /api/metrics/queues` - Queue depth and latency metrics
  - Queue sizes, wait times, processing rates

### 5. Provider Management
**Problem:** Provider management endpoints are commented out in the code

- `GET /api/providers` - List all registered providers
- `GET /api/providers/{id}` - Get provider details and capabilities
- `POST /api/providers/{id}/enable` - Enable a disabled provider
- `POST /api/providers/{id}/disable` - Disable a provider
- `GET /api/providers/{id}/health` - Provider health check
- `PUT /api/providers/{id}/config` - Update provider configuration

## 🔧 Advanced Features

### 6. Template Management
**Problem:** Template system exists but lacks API exposure

- `GET /api/templates` - List available workflow templates
- `GET /api/templates/{id}` - Get template details
- `POST /api/templates` - Create new template from workflow
- `PUT /api/templates/{id}` - Update existing template
- `DELETE /api/templates/{id}` - Delete template
- `POST /api/templates/{id}/instantiate` - Create workflow from template

### 7. Scheduling
**Problem:** No support for scheduled or recurring workflows

- `POST /api/schedules` - Create scheduled workflow execution
- `GET /api/schedules` - List all scheduled workflows
- `GET /api/schedules/{id}` - Get schedule details
- `PUT /api/schedules/{id}` - Update schedule (cron expression, parameters)
- `DELETE /api/schedules/{id}` - Cancel scheduled workflow
- `POST /api/schedules/{id}/trigger` - Manually trigger scheduled workflow

### 8. Queue Management
**Problem:** No administrative control over task queues

- `GET /api/queues` - List all queues and their status
- `GET /api/queues/{name}` - Get detailed queue statistics
- `POST /api/queues/{name}/pause` - Pause queue processing
- `POST /api/queues/{name}/resume` - Resume queue processing
- `POST /api/queues/{name}/clear` - Clear all tasks from queue
- `PUT /api/queues/{name}/config` - Update queue configuration (size, priority)

## 🔄 Batch Operations

### 9. Bulk Operations
**Problem:** No efficient way to manage multiple tasks/workflows

- `POST /api/tasks/bulk/cancel` - Cancel multiple tasks by IDs or filter
- `POST /api/tasks/bulk/retry` - Retry multiple failed tasks
- `POST /api/workflows/bulk/cancel` - Cancel multiple workflows
- `DELETE /api/workflows/bulk` - Delete multiple completed workflows
- `GET /api/tasks/bulk/status` - Get status of multiple tasks

## 📁 Data Management

### 10. Import/Export
**Problem:** No way to backup or migrate workflows and data

- `GET /api/workflows/{id}/export` - Export workflow definition as YAML/JSON
- `POST /api/workflows/import` - Import workflow from file
- `GET /api/data/export` - Export all system data (workflows, tasks, results)
- `POST /api/data/import` - Import system data from backup
- `GET /api/workflows/{id}/clone` - Clone existing workflow

### 11. Resource Management
**Problem:** No visibility or control over resource limits and quotas

- `GET /api/resources/limits` - Get current resource limits
- `PUT /api/resources/limits` - Update resource limits (CPU, memory, concurrent tasks)
- `GET /api/resources/usage` - Current resource usage statistics
- `GET /api/resources/quotas` - User/project quotas
- `PUT /api/resources/quotas` - Update quotas

### 12. Workflow Dependencies
**Problem:** No API access to dependency information and visualization

- `GET /api/workflows/{id}/dependencies` - Get dependency graph
- `GET /api/workflows/{id}/dependents` - Get workflows that depend on this one
- `POST /api/workflows/{id}/dependencies/validate` - Validate dependency chain
- `GET /api/workflows/{id}/critical-path` - Get critical path through workflow

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

### Quick Wins
- Task logs endpoint (partially implemented, needs completion)
- Provider management (code exists but is commented out)
- Basic retry endpoints (retry logic exists in the engine)

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

## 📅 Suggested Implementation Order

1. **Phase 1:** Complete partially implemented features
   - Task logs (real implementation)
   - Provider management (uncomment and test)
   - Basic retry endpoints

2. **Phase 2:** Core orchestration features
   - Workflow pause/resume
   - Task retry/rerun
   - Template CRUD operations

3. **Phase 3:** Monitoring and administration
   - Metrics endpoints
   - Queue management
   - Bulk operations

4. **Phase 4:** Advanced features
   - Scheduling system
   - Import/export
   - Resource management

This roadmap would bring Gleitzeit to feature parity with other workflow orchestration systems while maintaining its unique architecture and capabilities.