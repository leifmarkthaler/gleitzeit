# UI-API Alignment Check

## Executive Summary

After updating the UI authentication to use auto-login, checking if all UI endpoints properly align with the actual API endpoints.

## Alignment Status

### ✅ Authentication Endpoints (ALIGNED)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `/api/auth/me` | `/auth/me` | ✅ | Correctly updated to use this |
| `/api/auth/login` | `/auth/login` | ✅ | Works with auto-login |
| `/api/auth/logout` | `/auth/logout` | ✅ | Proper session cleanup |

### ✅ Workflow Endpoints (ALIGNED)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `GET /api/workflows` | `/workflows` | ✅ | List workflows |
| `POST /api/workflows` | `/workflows` | ✅ | Submit workflow |
| `GET /api/workflows/{id}` | `/workflows/{id}` | ✅ | Get workflow |
| `DELETE /api/workflows/{id}` | `/workflows/{id}` | ✅ | Delete workflow |
| `POST /api/workflows/{id}/cancel` | `/workflows/{id}/cancel` | ✅ | Cancel workflow |
| `POST /api/workflows/{id}/pause` | `/workflows/{id}/pause` | ✅ | Pause workflow |
| `POST /api/workflows/{id}/resume` | `/workflows/{id}/resume` | ✅ | Resume workflow |
| `POST /api/workflows/upload` | N/A | ❌ | Not in API |
| `POST /api/bulk/directory` | N/A | ❌ | Not in API |

### ✅ Task Endpoints (ALIGNED)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `GET /api/tasks` | `/tasks` | ✅ | List tasks |
| `POST /api/tasks/{id}/cancel` | `/tasks/{id}/cancel` | ✅ | Cancel task |
| `POST /api/tasks/{id}/retry` | `/tasks/{id}/retry` | ✅ | Retry task |
| `DELETE /api/tasks/{id}` | `/tasks/{id}` | ✅ | Delete task |

### ❌ Queue Endpoints (NOT IN API)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `GET /api/queues` | N/A | ❌ | Queues router not found |
| `GET /api/queues/{name}` | N/A | ❌ | Not implemented |
| `POST /api/queues/{name}/pause` | N/A | ❌ | Not implemented |
| `POST /api/queues/{name}/resume` | N/A | ❌ | Not implemented |
| `POST /api/queues/{name}/clear` | N/A | ❌ | Not implemented |
| `PUT /api/queues/{name}/config` | N/A | ❌ | Not implemented |

### ✅ Error Endpoints (ALIGNED)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `GET /api/event-errors` | `/event-errors` | ✅ | List errors |
| `GET /api/event-errors/stats` | `/event-errors/stats` | ✅ | Error statistics |
| `GET /api/event-errors/{id}` | `/event-errors/{id}` | ✅ | Get error details |
| `DELETE /api/event-errors/cleanup` | N/A | ❌ | Uses `/event-errors` DELETE |

### ✅ Log Endpoints (ALIGNED)
| UI Call | API Endpoint | Status | Notes |
|---------|--------------|--------|-------|
| `GET /api/logs` | `/logs` | ✅ | Available if logs router included |
| `GET /api/logs/stats` | `/logs/stats` | ✅ | Log statistics |

## Issues Found

### 1. Missing Queue Management API
The UI has a complete queue management interface but there's no `/queues` router in the API. The UI expects:
- List queues
- Get queue details
- Pause/resume queues
- Clear queues
- Configure queues

**Impact**: Queue management UI won't work

### 2. Missing Bulk Operations
The UI has bulk operation features that don't exist in the API:
- `/api/workflows/upload` - Upload multiple workflows
- `/api/bulk/directory` - Process directory of workflows

**Impact**: Bulk upload features won't work

### 3. Error Cleanup Endpoint Mismatch
- UI calls: `DELETE /api/event-errors/cleanup?days=X`
- API has: `DELETE /api/event-errors` with different params

**Impact**: Error cleanup might not work as expected

## Recommendations

### Priority 1: Fix Critical Misalignments
1. **Queue Management**: Either:
   - Remove queue UI if not needed
   - Implement queue API endpoints
   - Update UI to use task queue endpoints if those exist

2. **Bulk Operations**: Either:
   - Remove bulk upload UI
   - Implement bulk endpoints in API

### Priority 2: Fix Minor Issues
1. **Error Cleanup**: Update UI to use correct DELETE endpoint
2. **Auth Status**: Remove references to `/api/auth/status` completely

### Priority 3: Enhancement
1. Add API endpoint discovery/documentation endpoint
2. Add feature flags to hide UI elements for unimplemented endpoints

## Summary

**Aligned**: 
- ✅ Authentication (after our fixes)
- ✅ Workflows (mostly)
- ✅ Tasks
- ✅ Errors (mostly)
- ✅ Logs

**Not Aligned**:
- ❌ Queue Management (entire feature missing from API)
- ❌ Bulk Operations (upload features missing)
- ❌ Some utility endpoints

The UI expects more features than the API currently provides, particularly around queue management and bulk operations. The authentication is now properly aligned after our updates.