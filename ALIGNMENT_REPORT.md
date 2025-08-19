# Gleitzeit Component Alignment Report

## Overview
This report analyzes the alignment between CLI, API, and Client components in terms of functionality and hub architecture integration.

## Hub Architecture Integration

### Resource Manager Initialization

| Component | Resource Manager ID | Default State | Configuration Option |
|-----------|-------------------|---------------|---------------------|
| **CLI** | `cli-resources` | **Enabled by default** | `--no-resource-management` flag to disable |
| **API** | `api-resources` | **Always enabled** | No option to disable |
| **Client** | `client-resources` | **Disabled by default** | `native_config={'enable_resource_management': True}` to enable |

**⚠️ MISALIGNMENT**: Client has resource management disabled by default while CLI has it enabled by default.

### Provider Registration

All three components register providers consistently:

| Provider | CLI ID | API ID | Client ID | Hub Support |
|----------|--------|--------|-----------|-------------|
| Python | `cli-python-provider` | `api-python-provider` | `python-provider` | ✅ Docker hub (optional) |
| Ollama | `cli-ollama-provider` | `api-ollama-provider` | `ollama-provider` | ✅ Ollama hub |
| MCP | `cli-mcp-provider` | `api-mcp-provider` | `mcp-provider` | ❌ No hub |
| Template | `cli-template-provider` | `api-template-provider` | `template-provider` | ❌ No hub |

**✅ ALIGNED**: All components pass hub and resource_manager to providers consistently.

### OllamaHub Configuration

| Component | Auto-Discovery | Persistence Support |
|-----------|---------------|-------------------|
| **CLI** | ✅ Enabled | ✅ Uses persistence backend |
| **API** | ✅ Enabled | ✅ Uses persistence backend |
| **Client** | ✅ Enabled | ❌ No persistence passed |

**⚠️ MISALIGNMENT**: Client doesn't pass persistence to OllamaHub.

## Functional Alignment

### Core Workflow Operations

| Operation | CLI | API | Client (Native) | Client (API) |
|-----------|-----|-----|----------------|--------------|
| Run workflow from file | ✅ `run` | ✅ `/workflows/upload` | ✅ `run_workflow()` | ✅ `run_workflow()` |
| Submit workflow | ❌ | ✅ `/workflows` | ❌ | ✅ via API |
| Get workflow status | ❌ | ✅ `/workflows/{id}` | ✅ `get_workflow()` | ✅ via API |
| Cancel workflow | ❌ | ✅ `/workflows/{id}` DELETE | ❌ | ✅ via API |

### Task Operations

| Operation | CLI | API | Client (Native) | Client (API) |
|-----------|-----|-----|----------------|--------------|
| Submit task | ❌ | ✅ `/tasks` | ✅ `submit_task()` | ✅ via API |
| Execute task | ❌ | ✅ `/tasks` | ✅ `execute_task()` | ✅ via API |
| Get task status | ❌ | ✅ `/tasks/{id}` | ✅ `get_task_status()` | ✅ via API |
| Cancel task | ❌ | ❌ | ✅ `cancel_task()` | ❌ |

**⚠️ MISALIGNMENT**: Client has `cancel_task()` but API doesn't provide endpoint.

### LLM Operations

| Operation | CLI | API | Client |
|-----------|-----|-----|--------|
| Chat | ✅ via workflow | ✅ `/chat` | ✅ `chat()` |
| Batch processing | ✅ `batch` command | ✅ `/batch` | ✅ `batch_process()` |

**✅ ALIGNED**: All support chat and batch operations.

### Resource Management Operations

| Operation | CLI | API | Client |
|-----------|-----|-----|--------|
| View resource status | ✅ `status --resources` | ✅ `/resources` | ✅ `get_resource_metrics()` |
| Create resource pool | ❌ | ❌ | ✅ `create_resource_pool()` |
| Register resource | ❌ | ❌ | ✅ `register_resource()` |
| Allocate resource | ❌ | ❌ | ✅ `allocate_resource()` |
| Enable auto-scaling | ❌ | ❌ | ✅ `enable_auto_scaling()` |

**⚠️ MISALIGNMENT**: Client has advanced resource management methods not available in CLI/API.

### System Operations

| Operation | CLI | API | Client |
|-----------|-----|-----|--------|
| Status/Health check | ✅ `status` | ✅ `/status`, `/health` | ✅ `health_check()` |
| List providers | ❌ | ✅ `/providers` | ❌ |
| List protocols | ❌ | ✅ `/protocols` | ❌ |
| Cleanup old data | ❌ | ❌ | ✅ `cleanup_old_data()` |

## Missing Python Script Execution

**⚠️ CRITICAL MISALIGNMENT**: 

The Client documentation mentions `execute_python()` but this method doesn't exist. Instead, Python execution happens through:
- **CLI**: Via workflows with `python/execute` method
- **API**: Via `/tasks` with `protocol: "python/v1"`
- **Client**: Via `submit_task()` or `execute_task()` with `protocol: "python/v1"`

## Recommendations

### High Priority Fixes

1. **Align Resource Management Defaults**:
   - Change Client to enable resource management by default (matching CLI)
   - OR add configuration option to API to disable resource management
   
2. **Fix Client OllamaHub Persistence**:
   - Pass persistence backend to OllamaHub in Client

3. **Add Missing API Endpoints**:
   - Add `DELETE /tasks/{id}` for task cancellation
   - Consider adding resource management endpoints

4. **Remove/Update Incorrect Documentation**:
   - Remove references to `execute_python()` method
   - Update docs to show correct Python execution approach

### Medium Priority Enhancements

1. **Unify Provider IDs**:
   - Consider using consistent provider IDs across all components
   
2. **Add Missing CLI Features**:
   - Add ability to submit individual tasks
   - Add provider/protocol listing commands

3. **Expose Resource Management**:
   - Consider exposing resource pool management in API
   - Add CLI commands for resource management

### Low Priority Nice-to-Haves

1. **Workflow Management**:
   - Add workflow cancellation to CLI
   - Add workflow status tracking to CLI

2. **System Maintenance**:
   - Add cleanup command to CLI
   - Add cleanup endpoint to API

## Summary

The three components are **mostly aligned** in core functionality with hub architecture properly integrated. Main issues:

1. **Resource management defaults differ** (Client disabled, others enabled)
2. **Client missing persistence for OllamaHub**
3. **Some methods exist only in Client** (resource management, task cancellation)
4. **Documentation references non-existent methods** (`execute_python()`)

The hub architecture is consistently implemented across all three components, with only minor configuration differences that should be addressed for full alignment.