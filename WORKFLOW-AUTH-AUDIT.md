# Workflow Authorization Audit

## Current Issues

### CRITICAL: Workflows Being Submitted Without User ID
- **Problem**: Workflows are reaching execution without a user_id set
- **Security Risk**: This bypasses authorization entirely
- **Root Cause**: The authentication chain is broken - user context isn't being properly passed through to SystemManager

## Authorization Flow Analysis

### 1. API Layer (`/api/routes/workflows.py`)

#### Submit Workflow Endpoint
```python
@router.post("/", response_model=Dict[str, Any])
async def submit_workflow(
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager),
    workflow: Dict[str, Any] = Body(..., embed=True)
):
```

**Issues:**
- ✅ Gets credentials from request
- ✅ Gets client with auth context via `get_client` dependency
- ❌ Doesn't verify user context is set before submission
- ❌ Doesn't pass user context to SystemManager explicitly

#### Get Workflow Endpoint
```python
@router.get("/{workflow_id}", response_model=Optional[Workflow])
async def get_workflow(
    workflow_id: str,
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    client: GleitzeitClient = Depends(get_client),
    system_manager = Depends(get_system_manager)
):
    current_user = await get_current_user(req, credentials, system_manager)
    workflow = await check_workflow_ownership(workflow_id, current_user, client, "read")
```

**Issues:**
- ❌ Authorization check happens in API layer, not SystemManager
- ❌ Uses client to get workflow, which then calls back to API (circular)
- ❌ Should delegate all auth to SystemManager

### 2. Client Layer (`/client/adapters/native.py`)

#### Submit Workflow
```python
async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
    workflow_id = await self.workflow_manager.submit_workflow(workflow)
```

**Issues:**
- ❌ No user context passed with workflow
- ❌ Direct access to WorkflowManager bypasses AuthManager
- ❌ Should go through SystemManager's authenticated submission method

#### Get Workflow
```python
async def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
    workflow = await self.persistence.get_workflow(workflow_id)
    if workflow and self.user_context:
        if not await self._check_workflow_access(workflow, "read"):
            raise AuthorizationError(...)
```

**Issues:**
- ❌ Client doing authorization checks (should be SystemManager)
- ❌ Direct persistence access bypasses SystemManager
- ❌ Duplicate auth logic in client and API

### 3. SystemManager Layer (`/system/system_manager.py`)

**Current State:**
- Has AuthManager instance
- Has WorkflowManager instance  
- But they're not properly integrated!

**Missing:**
- ❌ No authenticated workflow submission method
- ❌ No user context tracking with sessions
- ❌ AuthManager not consulted for workflow operations

### 4. AuthManager (`/auth/auth_manager.py`)

**Current State:**
- Creates sessions
- Returns basic user in basic mode
- But sessions aren't tracked with operations!

**Missing:**
- ❌ Session-to-user mapping not used for workflow operations
- ❌ No method to get user from session for workflow ownership

## Correct Architecture

### Single Authorization Path Through SystemManager

```
Client/API/CLI
     ↓
SystemManager (with session)
     ↓
AuthManager.authorize_operation(session, resource, action)
     ↓
WorkflowManager.submit_workflow(workflow, user_context)
```

### Required Changes

#### 1. SystemManager Needs Authenticated Methods

```python
class SystemManager:
    async def submit_workflow_authenticated(
        self, 
        workflow: Workflow, 
        session_id: str
    ) -> str:
        # Get user from session via AuthManager
        user = await self.auth_manager.get_user_from_session(session_id)
        if not user:
            raise AuthenticationError("Invalid session")
        
        # Set ownership
        workflow.user_id = user['id']
        
        # Submit through WorkflowManager
        return await self.workflow_manager.submit_workflow(workflow)
    
    async def get_workflow_authenticated(
        self,
        workflow_id: str,
        session_id: str
    ) -> Optional[Workflow]:
        # Get user from session
        user = await self.auth_manager.get_user_from_session(session_id)
        
        # Get workflow
        workflow = await self.persistence.get_workflow(workflow_id)
        if not workflow:
            return None
        
        # Check authorization via AuthManager
        if not await self.auth_manager.authorize_resource(
            user, f"workflow/{workflow_id}", "read"
        ):
            raise AuthorizationError(
                resource=f"workflow/{workflow_id}",
                action="read",
                reason="Access denied"
            )
        
        return workflow
```

#### 2. Client Should Pass Session ID

```python
class NativeAdapter:
    async def submit_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        # Get session from service token or user context
        session_id = self._get_session_id()
        
        # Call SystemManager's authenticated method
        workflow_id = await self.system_manager.submit_workflow_authenticated(
            workflow, session_id
        )
```

#### 3. API Should Use Session from Request

```python
@router.post("/")
async def submit_workflow(
    req: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    system_manager = Depends(get_system_manager),
    workflow: Dict[str, Any] = Body(..., embed=True)
):
    # Get session from credentials or create basic session
    session_id = await get_session_id(req, credentials, system_manager)
    
    # Submit through SystemManager with session
    workflow_obj = Workflow(**workflow)
    workflow_id = await system_manager.submit_workflow_authenticated(
        workflow_obj, session_id
    )
```

#### 4. Remove Duplicate Authorization Logic

- Remove `check_workflow_ownership` from `/api/authorization.py`
- Remove `_check_workflow_access` from `/client/adapters/native.py`
- All authorization goes through `SystemManager.AuthManager`

## Security Requirements

1. **No Workflow Without User**: Every workflow MUST have a user_id
2. **Single Auth Path**: All auth checks through SystemManager.AuthManager
3. **Session-Based**: Operations tied to sessions, not passed user objects
4. **No Client Auth**: Clients are thin layers, no authorization logic
5. **No API Auth**: API routes forward to SystemManager, no auth checks

## Testing Required

1. Submit workflow in basic mode → should get basic-user ID
2. Submit workflow with auth → should get authenticated user ID  
3. Get workflow as owner → should succeed
4. Get workflow as non-owner → should fail (except admin)
5. Submit workflow without any auth → should fail

## Conclusion

The current implementation has authorization logic scattered across layers:
- API does auth checks
- Client does auth checks
- SystemManager doesn't do auth checks!

This needs to be inverted - SystemManager should be the ONLY place doing authorization through its AuthManager.