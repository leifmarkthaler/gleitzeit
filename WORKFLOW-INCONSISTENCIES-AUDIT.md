# Workflow Inconsistencies Audit

## Overview
After implementing centralized validation and ID generation in SystemManager, this audit identifies remaining workflow-related inconsistencies across the system.

## Critical Security Issues

### 1. ❌ Batch Workflow Submission - No Authentication
- **File**: `src/gleitzeit/api/routes/workflows.py:237-244`
- **Issue**: `/workflows/batch` endpoint bypasses authentication entirely
- **Code**:
```python
@router.post("/batch", response_model=List[Dict[str, Any]])
async def submit_workflows_batch(
    workflows: List[WorkflowSubmissionRequest],
    client: GleitzeitClient = Depends(get_client)  # No auth dependencies!
):
```
- **Impact**: CRITICAL - Anyone can submit multiple workflows without authentication
- **Should be**: Use SystemManager.submit_workflow_authenticated() for each workflow

### 2. ❌ YAML File Upload - No Authentication  
- **File**: `src/gleitzeit/api/routes/workflows.py:247-254`
- **Issue**: `/workflows/from-yaml` endpoint bypasses authentication
- **Code**:
```python
@router.post("/from-yaml", response_model=Dict[str, Any])
async def submit_workflow_from_yaml(
    yaml_file: UploadFile = File(...),
    client: GleitzeitClient = Depends(get_client)  # No auth dependencies!
):
```
- **Impact**: CRITICAL - Anyone can upload and execute workflow files

### 3. ❌ Workflow Results - No Authorization Check
- **File**: `src/gleitzeit/api/routes/workflows.py:228-234`
- **Issue**: Anyone can access any workflow's results
- **Code**:
```python
@router.get("/{workflow_id}/results", response_model=Dict[str, Any])
async def get_workflow_results(
    workflow_id: str,
    client: GleitzeitClient = Depends(get_client)  # No ownership check!
):
```
- **Impact**: HIGH - Data leakage, users can access other users' workflow results

### 4. ❌ Workflow Retry - No Authorization Check
- **File**: `src/gleitzeit/api/routes/workflows.py:266-272`
- **Issue**: Anyone can retry any workflow
- **Impact**: MEDIUM - Users can interfere with other users' workflows

## Validation Inconsistencies

### 5. ❌ Batch Submission Bypasses Validation
- **File**: `src/gleitzeit/api/routes/workflows.py:243`
- **Issue**: Creates Workflow objects directly, bypasses WorkflowLoaderV2
- **Code**:
```python
workflow_objects = [Workflow(**w.workflow) for w in workflows]  # No validation!
```
- **Impact**: Invalid workflows can be submitted in batch, bypassing all validation

### 6. ❌ YAML Upload Bypasses SystemManager
- **Issue**: Uses client.submit_workflow_yaml() instead of SystemManager
- **Impact**: Bypasses centralized validation, ID generation, and user ownership

### 7. ❌ File Upload Size Limits
- **Issue**: YAML file upload has no size validation
- **Impact**: Large files could cause memory/performance issues

## Architecture Inconsistencies  

### 8. ❌ Mixed Client/SystemManager Usage
- **Pattern**: Some endpoints use SystemManager (good), others use client directly (bad)
- **Good**: `submit_workflow()` → SystemManager → WorkflowLoaderV2
- **Bad**: `submit_workflows_batch()` → client → bypasses validation
- **Impact**: Inconsistent validation, authentication, and logging

### 9. ❌ Inconsistent Error Handling
- **Issue**: Batch operations don't use centralized error management
- **Impact**: Different error formats for batch vs single workflow operations

## Missing Authorization Checks

### 10. ❌ Export Workflow - No Authorization
- **File**: `src/gleitzeit/api/routes/workflows.py:275-282`
- **Issue**: Anyone can export any workflow definition

### 11. ❌ Clone Workflow - No Authorization  
- **File**: `src/gleitzeit/api/routes/workflows.py:285-291`
- **Issue**: Anyone can clone any workflow

### 12. ❌ Get Workflow Dependencies - No Authorization
- **File**: `src/gleitzeit/api/routes/workflows.py:294-300`
- **Issue**: Anyone can access workflow dependency information

## Missing Client Methods

### 13. ❌ Client Library Missing Batch Methods
- **Issue**: Client library has no `submit_workflows_batch()` or `submit_workflow_yaml()` methods
- **Impact**: API endpoints exist but no client library support

## Recommendations

### Critical Fixes (Security)

1. **Fix Batch Endpoint Authentication**:
```python
@router.post("/batch", response_model=List[Dict[str, Any]])
async def submit_workflows_batch(
    workflows: List[WorkflowSubmissionRequest],
    req: Request,
    response: Response,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    
    results = []
    for workflow_req in workflows:
        workflow_id = await system_manager.submit_workflow_authenticated(
            workflow_req.workflow, session_id
        )
        results.append({"success": True, "workflow_id": workflow_id})
    return results
```

2. **Fix YAML Upload Authentication**:
```python
@router.post("/from-yaml", response_model=Dict[str, Any])
async def submit_workflow_from_yaml(
    yaml_file: UploadFile = File(...),
    req: Request,
    response: Response, 
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager)
):
    # Validate file size
    content = await yaml_file.read()
    if len(content) > 10_000_000:  # 10MB limit
        raise HTTPException(413, "File too large")
    
    # Parse YAML and submit through SystemManager
    import yaml
    workflow_dict = yaml.safe_load(content.decode())
    
    session_id = await get_or_create_session_id(req, response, credentials, system_manager)
    workflow_id = await system_manager.submit_workflow_authenticated(workflow_dict, session_id)
    
    return {"success": True, "workflow_id": workflow_id}
```

3. **Add Authorization to All Read Operations**:
   - Add ownership checks to `/workflows/{id}/results`, `/workflows/{id}/export`, etc.
   - Use pattern from existing operations like cancel/pause/resume

### Architecture Fixes

4. **Standardize All Endpoints**:
   - All workflow operations should go through SystemManager
   - All operations should have proper authentication
   - All operations should use centralized error handling

5. **Add Missing Client Methods**:
   - Add `submit_workflows_batch()` and `submit_workflow_yaml()` to client library
   - Ensure they follow the same authentication patterns

## Summary

**Critical Security Issues**: 4 endpoints with no authentication
**Validation Issues**: 3 endpoints bypass proper validation  
**Authorization Issues**: 6 endpoints missing ownership checks

**Priority Order**:
1. Fix batch and YAML upload authentication (CRITICAL)
2. Add authorization checks to read operations (HIGH)
3. Standardize validation flow (MEDIUM)
4. Add missing client methods (LOW)