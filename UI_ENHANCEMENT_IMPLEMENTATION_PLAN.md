# Gleitzeit UI Enhancement Implementation Plan

**Version**: 0.0.7
**Date**: 2025-10-01
**Current Integration Coverage**: 43% (24/56 endpoints)
**Target Coverage**: 80%+ (45/56 endpoints)

---

## Executive Summary

This plan outlines the integration of 32 remaining API endpoints into the Gleitzeit UI. The implementation is organized into 5 phases prioritized by user impact and implementation effort. The goal is to provide full visibility into system operations without requiring CLI access.

### Recently Completed (Current Session) ✅

- **Logging System Integration** (5 endpoints)
  - `/system/logs` - All logs viewer
  - `/system/logs/errors` - Error logs viewer
  - `/system/logs/stats` - Log statistics dashboard
  - `/system/logs/workflow/{workflow_id}` - Workflow-specific logs
  - `/tasks/{task_id}/logs` - Task-specific logs

---

## Phase 1: Critical User Experience Improvements ⭐

### 1.1 Workflow Submission Form

**Priority**: HIGH
**Effort**: Medium
**Endpoint**: `POST /workflows/submit`

**Current State**: Simple JavaScript prompt-based submission
**Target State**: Professional workflow submission form with validation

**Implementation Tasks**:

1. **Create Modal Component**
   - File: `/src/gleitzeit/ui/templates/components/workflow_submit_modal.html`
   - Features:
     - YAML/JSON editor with syntax highlighting
     - Workflow template selector (common patterns)
     - Client-side validation
     - Success/error feedback
     - Auto-fill workflow ID and direct link to submitted workflow

2. **Update Workflows List Page**
   - File: `/src/gleitzeit/ui/templates/workflows/list.html`
   - Replace `prompt()` call (line 154) with modal trigger
   - Add modal include at bottom of page
   - Enhance `submitWorkflow()` function with better error handling

3. **Add Template Library**
   - Create common workflow templates (simple task, parallel tasks, conditional, etc.)
   - Store in `/src/gleitzeit/ui/static/data/workflow_templates.json`

**Success Criteria**:
- Users can submit workflows without CLI
- Validation prevents common errors
- Templates reduce time to create workflows by 70%

---

### 1.2 Queue Monitoring Dashboard

**Priority**: HIGH
**Effort**: Medium
**Endpoint**: `GET /system/queues`

**Current State**: No queue visibility in UI
**Target State**: Real-time queue depth monitoring with alerts

**Implementation Tasks**:

1. **Add Queue Stats to Dashboard**
   - File: `/src/gleitzeit/ui/templates/index.html`
   - Add queue monitoring card after metrics card
   - Display queue depths by stream type:
     - `workflow:load`
     - `workflow:submitted`
     - `task:ready`
     - `task:completed`
     - Per-shard breakdown (collapsible)

2. **Update Dashboard Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Fetch queue data in `index()` function
   - Add to context: `context["queues"]`

3. **Add Visual Indicators**
   - Color-coded alerts:
     - Green: < 50 items
     - Yellow: 50-200 items
     - Red: > 200 items
   - Show queue trends (if historical data available)

4. **Auto-Refresh**
   - Update queue stats every 5 seconds
   - Use HTMX polling or JavaScript

**Success Criteria**:
- Queue depths visible on dashboard
- Alerts trigger for high queue depths
- Users can diagnose bottlenecks quickly

---

### 1.3 Enhanced Workers View

**Priority**: HIGH
**Effort**: Low
**Endpoint**: `GET /system/workers`

**Current State**: Basic worker info from `/system/status` on handlers page
**Target State**: Dedicated workers page with detailed metrics

**Implementation Tasks**:

1. **Create Workers List Page**
   - File: `/src/gleitzeit/ui/templates/workers/list.html` (new)
   - Display worker table with columns:
     - Worker ID
     - Worker Type
     - Status (healthy/unhealthy)
     - Assigned Shards
     - Messages Processed
     - Processing Rate (msgs/sec)
     - Error Rate
     - Last Heartbeat
     - Actions (manual health check)

2. **Add Workers Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Add `@app.get("/workers")` route
   - Fetch from `/system/workers` endpoint
   - Parse worker metrics

3. **Add Health Check Trigger**
   - Button to call `POST /system/workers/health-check`
   - Show confirmation and result

4. **Update Navigation**
   - File: `/src/gleitzeit/ui/templates/base.html`
   - Add "Workers" nav link (or replace "Handlers" with "Workers")

**Success Criteria**:
- Complete worker visibility
- Health status at a glance
- Manual health check capability

---

### 1.4 Logout Functionality

**Priority**: HIGH
**Effort**: Low
**Endpoint**: `POST /auth/session/destroy`

**Current State**: No logout option
**Target State**: Logout button in navigation

**Implementation Tasks**:

1. **Add Logout Button to Navigation**
   - File: `/src/gleitzeit/ui/templates/base.html`
   - Add logout button in nav-menu (after API Status)
   - Style as secondary/danger button

2. **Create Logout Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Add `@app.post("/logout")` route
   - Call `/auth/session/destroy` endpoint
   - Clear session cookie
   - Redirect to home or login page

3. **Handle Logout in Frontend**
   - JavaScript confirmation (optional)
   - Show logout success message
   - Clear any client-side cached data

**Success Criteria**:
- Users can logout from any page
- Session properly destroyed
- Redirect to appropriate page

---

## Phase 2: Advanced Monitoring & Metrics 📊

### 2.1 Detailed Metrics Views

**Priority**: MEDIUM
**Effort**: Medium
**Endpoints**: `GET /system/metrics/tasks`, `GET /system/metrics/workflows`

**Implementation Tasks**:

1. **Create Metrics Detail Page**
   - File: `/src/gleitzeit/ui/templates/metrics/detail.html` (new)
   - Tab-based interface:
     - Task Metrics tab
     - Workflow Metrics tab

2. **Task Metrics Tab**
   - Display from `/system/metrics/tasks`:
     - Total tasks executed
     - Completion rate (%)
     - Average execution time
     - Failure rate (%)
     - Tasks by type breakdown
     - Top failed task types

3. **Workflow Metrics Tab**
   - Display from `/system/metrics/workflows`:
     - Total workflows submitted
     - Success rate (%)
     - Average task count per workflow
     - Average workflow duration
     - Failed workflows count
     - Workflow status distribution

4. **Add Time Range Selector**
   - Options: Last Hour, Last Day, Last Week, All Time
   - Filter metrics by time range

5. **Optional: Charts/Graphs**
   - If adding chart library (Chart.js recommended):
     - Task completion trends over time
     - Workflow success/failure pie chart
     - Task execution time histogram

**Success Criteria**:
- Comprehensive metrics visibility
- Historical analysis capability
- Identify performance patterns

---

### 2.2 Audit Logs Viewer

**Priority**: MEDIUM
**Effort**: Medium
**Endpoint**: `GET /system/audit/logs`

**Implementation Tasks**:

1. **Create Audit Logs Page**
   - File: `/src/gleitzeit/ui/templates/audit/logs.html` (new)
   - Display audit events table:
     - Timestamp
     - User/Session
     - Action Type
     - Resource (workflow/task ID)
     - IP Address
     - Status (success/failure)
     - Details

2. **Add Filtering**
   - Filter by:
     - User/Session ID
     - Action type (workflow submit, task cancel, etc.)
     - Time range
     - Status (success/failure)

3. **Add Pagination**
   - Support for large audit logs
   - Limit 100 per page

4. **Add Export Functionality**
   - Export to CSV
   - Export to JSON
   - Export filtered results

5. **Add Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Add `@app.get("/audit")` route

**Success Criteria**:
- Full audit trail visibility
- Security compliance capability
- Troubleshooting support

---

### 2.3 System Configuration Viewer

**Priority**: MEDIUM
**Effort**: Low
**Endpoint**: `GET /system/config`

**Implementation Tasks**:

1. **Create Config Viewer Page**
   - File: `/src/gleitzeit/ui/templates/system/config.html` (new)
   - Display configuration in organized sections:
     - Redis Configuration
     - Handler Configuration
     - Worker Configuration
     - Sharding Configuration
     - Logging Configuration
     - Monitoring Configuration
     - Security Configuration

2. **Format Configuration**
   - YAML/JSON syntax highlighting
   - Collapsible sections
   - Search/filter capability

3. **Security: Mask Sensitive Values**
   - Hide JWT secrets
   - Mask API keys
   - Redact credentials
   - Show only last 4 chars: `****abcd`

4. **Show Effective vs Default**
   - Highlight overridden values
   - Show default values in gray
   - Indicate environment variable overrides

5. **Add Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Add `@app.get("/config")` route

**Success Criteria**:
- Configuration transparency
- Security maintained (no secret exposure)
- Easy diagnosis of config issues

---

### 2.4 Resource Monitoring

**Priority**: MEDIUM
**Effort**: Medium
**Endpoint**: `GET /system/resources`

**Implementation Tasks**:

1. **Add Resource Stats to Dashboard**
   - File: `/src/gleitzeit/ui/templates/index.html`
   - Add resource monitoring card showing:
     - CPU usage (%)
     - Memory usage (MB / GB)
     - Redis memory usage
     - Connection pool stats
     - Open file descriptors

2. **Update Dashboard Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Fetch from `/system/resources`
   - Add to dashboard context

3. **Add Visual Indicators**
   - Progress bars for percentage metrics
   - Color-coded alerts:
     - Green: < 70% usage
     - Yellow: 70-90% usage
     - Red: > 90% usage

4. **Optional: Historical Graphs**
   - If implementing charts:
     - CPU usage over time
     - Memory usage trends
     - Connection pool utilization

**Success Criteria**:
- Resource usage visibility
- Early warning for resource exhaustion
- Performance optimization support

---

## Phase 3: Workflow Visualization 🔄

### 3.1 Task Dependency Graph

**Priority**: MEDIUM
**Effort**: High
**Endpoints**:
- `GET /workflows/{workflow_id}/tasks/{task_id}/dependencies`
- `GET /workflows/{workflow_id}/tasks/{task_id}/dependents`

**Implementation Tasks**:

1. **Choose Graph Library**
   - Recommended: Mermaid.js (simple, no heavy dependencies)
   - Alternative: D3.js (more powerful, steeper learning curve)
   - Alternative: vis.js (good balance)

2. **Create Workflow Graph Component**
   - File: `/src/gleitzeit/ui/templates/workflows/graph.html` (new)
   - Or add as tab in workflow detail page
   - Features:
     - DAG visualization
     - Node colors by task status (pending/running/completed/failed)
     - Interactive: click node to view task details
     - Highlight critical path
     - Show task dependencies and dependents

3. **Add Graph Route or Tab**
   - Option A: Separate page `/workflows/{workflow_id}/graph`
   - Option B: Add "Graph" tab to workflow detail page (recommended)

4. **Fetch Dependencies for All Tasks**
   - Query all tasks in workflow
   - Build dependency map
   - Generate graph data structure

5. **Add JavaScript for Rendering**
   - File: `/src/gleitzeit/ui/static/js/workflow-graph.js` (new)
   - Render graph from data
   - Handle click events
   - Auto-layout algorithm

**Success Criteria**:
- Visual workflow understanding
- Quick identification of blocked tasks
- Interactive task navigation

---

### 3.2 Task Cancellation

**Priority**: LOW
**Effort**: Low
**Endpoint**: `POST /tasks/{task_id}/cancel`

**Implementation Tasks**:

1. **Add Cancel Button to Task Detail**
   - File: `/src/gleitzeit/ui/templates/tasks/detail.html`
   - Add cancel button next to retry button
   - Only show for running/pending tasks

2. **Implement Cancellation**
   - Add JavaScript function `cancelTask()`
   - Call `/api/tasks/{task_id}/cancel`
   - Show confirmation dialog
   - Display success/error message

3. **Update Task State**
   - Refresh task detail after cancellation
   - Show "cancelled" status badge

**Success Criteria**:
- Tasks can be cancelled from UI
- Confirmation prevents accidental cancellation
- State updates immediately

---

## Phase 4: Admin & Cluster Features 🔧

### 4.1 Health Checks Dashboard

**Priority**: LOW
**Effort**: Medium
**Endpoints**:
- `GET /health/`
- `GET /health/live`
- `GET /health/ready`
- `GET /health/detailed`
- `GET /health/cluster`

**Implementation Tasks**:

1. **Create Health Dashboard Page**
   - File: `/src/gleitzeit/ui/templates/health/dashboard.html` (new)
   - Display health check results:
     - Overall system health (healthy/degraded/unhealthy)
     - Component-by-component status
     - Liveness indicator
     - Readiness indicator
     - Cluster health (if clustered)

2. **Add Health Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Fetch all health endpoints
   - Aggregate results

3. **Visual Health Status**
   - Large status indicator at top
   - Traffic light colors (green/yellow/red)
   - Detailed breakdown below

4. **Auto-Refresh**
   - Update health status every 10 seconds

**Success Criteria**:
- Quick health assessment
- Component failure identification
- Operational status visibility

---

### 4.2 Service Discovery View

**Priority**: LOW
**Effort**: Medium
**Endpoints**:
- `GET /discovery/services/{service_type}`
- `GET /discovery/health/{service_type}`

**Implementation Tasks**:

1. **Create Service Discovery Page**
   - File: `/src/gleitzeit/ui/templates/discovery/services.html` (new)
   - List all service types:
     - API
     - UI
     - Workers
   - For each service type, show instances:
     - Instance ID
     - Host/Port
     - Health Status
     - Registered Time
     - Last Heartbeat

2. **Add Services Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Fetch service types
   - Fetch instances for each type
   - Fetch health for each instance

3. **Service Health Indicators**
   - Color-coded health status
   - Show instance details on click

**Success Criteria**:
- Service visibility in cluster
- Instance health monitoring
- Service discovery debugging

---

### 4.3 Active Sessions Viewer

**Priority**: LOW
**Effort**: Low
**Endpoint**: `GET /system/sessions`

**Implementation Tasks**:

1. **Create Sessions Management Page**
   - File: `/src/gleitzeit/ui/templates/system/sessions.html` (new)
   - Display active sessions table:
     - Session ID
     - User (if available)
     - IP Address
     - Created Time
     - Last Activity
     - Expires At
     - Actions (admin: terminate)

2. **Add Sessions Route**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Fetch from `/system/sessions`

3. **Add Filtering**
   - Filter by user
   - Filter by active/expired

4. **Admin Actions (Optional)**
   - Force terminate session
   - Requires admin privileges

**Success Criteria**:
- Session visibility for security
- Identify unauthorized sessions
- Session management capability

---

## Phase 5: Polish & UX Enhancements ✨

### 5.1 Improved Navigation

**Implementation Tasks**:

1. **Add Breadcrumb Navigation**
   - File: `/src/gleitzeit/ui/templates/base.html`
   - Show current location hierarchy
   - Example: `Home > Workflows > workflow-123 > task-456`

2. **Quick Search**
   - Add search box in navigation
   - Search by workflow ID or task ID
   - Auto-complete suggestions
   - Jump directly to resource

3. **Recent Items Dropdown**
   - Track recently viewed workflows/tasks
   - Store in localStorage
   - Quick access dropdown in nav

4. **Keyboard Shortcuts**
   - Add common shortcuts:
     - `/` - Focus search
     - `g w` - Go to workflows
     - `g t` - Go to tasks
     - `g l` - Go to logs
     - `?` - Show help

**Success Criteria**:
- Navigation is intuitive
- Quick access to common actions
- Power users are more efficient

---

### 5.2 Better Error Handling

**Implementation Tasks**:

1. **Unified Error Display Component**
   - File: `/src/gleitzeit/ui/templates/components/error.html` (new)
   - Consistent error styling
   - Error types: API error, validation error, network error
   - Actions: Retry, dismiss, report

2. **Retry Failed API Calls**
   - Automatic retry with exponential backoff
   - Max 3 retries
   - Show retry attempts to user

3. **Connection Loss Detection**
   - Monitor API connectivity
   - Show banner when disconnected
   - Auto-reconnect when connection restored

4. **Graceful Degradation**
   - Handle partial failures
   - Show what's available when some features fail
   - Cache data for offline viewing

**Success Criteria**:
- Users understand errors clearly
- Transient failures auto-recover
- System remains usable during issues

---

### 5.3 Real-time Updates

**Implementation Tasks**:

1. **Implement WebSocket Connection**
   - File: `/src/gleitzeit/ui/api/app.py`
   - Upgrade WebSocket endpoint from echo to real updates
   - Connect to API WebSocket (if available)

2. **Real-time Workflow Status**
   - Push workflow state changes to clients
   - Update workflow list without refresh
   - Show live progress on workflow detail

3. **Live Log Streaming**
   - Stream new logs as they arrive
   - Auto-scroll to latest (with pause option)
   - Highlight new entries

4. **Push Notifications**
   - Browser notifications for:
     - Workflow completion
     - Workflow failure
     - Critical errors
   - User can enable/disable per event type

**Success Criteria**:
- No manual refresh needed
- Instant status updates
- Enhanced monitoring experience

---

## Implementation Order Recommendation

### Week 1: Foundation
- [x] 1.4 Logout Functionality (Quick win)
- [ ] 1.2 Queue Monitoring Dashboard
- [ ] 1.3 Enhanced Workers View

### Week 2: Core Features
- [ ] 1.1 Workflow Submission Form
- [ ] 2.4 Resource Monitoring
- [ ] 2.3 System Configuration Viewer

### Week 3: Advanced Features
- [ ] 2.1 Detailed Metrics Views
- [ ] 2.2 Audit Logs Viewer
- [ ] 3.2 Task Cancellation

### Week 4: Visualization
- [ ] 3.1 Task Dependency Graph
- [ ] 5.1 Navigation Improvements
- [ ] 5.2 Error Handling

### Future Iterations
- [ ] Phase 4: Admin & Cluster Features
- [ ] 5.3 Real-time Updates

---

## Success Metrics

### Coverage
- **Current**: 43% (24/56 endpoints)
- **Phase 1 Complete**: 50% (28/56 endpoints)
- **Phase 2 Complete**: 64% (36/56 endpoints)
- **Phase 3 Complete**: 68% (38/56 endpoints)
- **All Phases Complete**: 82% (46/56 endpoints)

### User Impact
- Enable all common workflows without CLI
- Reduce time to diagnose issues by 50%
- Increase user self-service from 40% to 90%

### Performance
- All pages load in < 2 seconds
- Real-time updates with < 1 second latency
- Support 100+ concurrent users

---

## Technical Dependencies

### Required (None - All endpoints exist)
- ✅ All API endpoints already implemented
- ✅ UI framework in place (FastAPI + Jinja2)
- ✅ Styling system established

### Optional (For Enhanced UX)

**Chart/Graph Libraries**:
- **Chart.js** (Recommended) - Simple, beautiful charts
  - CDN: `https://cdn.jsdelivr.net/npm/chart.js`
  - Size: ~60KB gzipped
  - Use for: Metrics visualization

- **Mermaid.js** (Recommended) - Diagram generation
  - CDN: `https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js`
  - Size: ~300KB gzipped
  - Use for: Workflow DAG graphs

**Code Editor** (For workflow submission):
- **CodeMirror** or **Monaco Editor**
  - Syntax highlighting for YAML/JSON
  - Code validation
  - Auto-completion

**Real-time** (For Phase 5.3):
- WebSocket support (already in FastAPI)
- Server-side event streaming

---

## Risk Assessment

### Low Risk
- Logout functionality
- Queue monitoring
- Workers view
- Config viewer
- Task cancellation

### Medium Risk
- Workflow submission form (requires good UX design)
- Metrics views (data aggregation complexity)
- Resource monitoring (performance impact)

### High Risk
- Task dependency graph (complex visualization)
- Real-time updates (scaling concerns)
- Audit logs (large data volume)

### Mitigation Strategies
- Start with low-risk items
- Prototype complex visualizations early
- Performance test real-time features
- Implement pagination for large datasets
- Add feature flags for gradual rollout

---

## Maintenance Considerations

### Ongoing
- Keep UI in sync with API changes
- Update when new endpoints added
- Maintain backward compatibility

### Documentation
- Update user documentation for each feature
- Create admin guide for new features
- Document API endpoint usage in UI

### Testing
- Add UI tests for critical flows
- Test with various screen sizes
- Browser compatibility testing
- Performance regression testing

---

## Appendix: Endpoint Reference

### ✅ Currently Integrated (24 endpoints)

**Authentication**:
- POST /auth/session/create

**Workflows**:
- GET /workflows/list
- GET /workflows/{workflow_id}
- GET /workflows/{workflow_id}/tasks
- POST /workflows/{workflow_id}/cancel

**Tasks**:
- GET /tasks/list
- POST /tasks/ (batch)
- GET /tasks/{task_id}
- GET /tasks/{task_id}/events
- GET /tasks/{task_id}/logs ✨
- POST /tasks/{task_id}/retry

**System**:
- GET /system/status
- GET /system/metrics
- GET /system/logs ✨
- GET /system/logs/errors ✨
- GET /system/logs/stats ✨
- GET /system/logs/workflow/{workflow_id} ✨

**Discovery**:
- GET /discovery/topology
- GET /discovery/machines
- GET /discovery/instance/current

### ❌ Not Yet Integrated (32 endpoints)

See implementation plan above for details on each endpoint.

---

## Document Revision History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2025-10-01 | Initial plan created | Claude |
| 1.1 | 2025-10-01 | Added logging endpoints to completed section | Claude |

---

## Next Steps

1. **Review and Prioritize**: Confirm priority ordering with stakeholders
2. **Allocate Resources**: Assign developers to phases
3. **Set Milestones**: Establish completion dates for each phase
4. **Begin Implementation**: Start with Phase 1, Week 1 tasks
5. **Iterative Feedback**: Review after each phase, adjust plan as needed

---

**Questions or Feedback?**
Contact the development team or create an issue in the project repository.
