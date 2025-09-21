"""
Authorization helpers for API routes.

This module provides resource ownership checking that works with
the client pooling architecture.
"""

import logging
from typing import Optional, Dict, Any
from fastapi import HTTPException

from gleitzeit.client import GleitzeitClient
from gleitzeit.core.models import Workflow, Task
from gleitzeit.auth.permissions import has_permission, Permissions
from gleitzeit.core.errors import (
    SystemError,
    ErrorCode,
    AuthorizationError
)

logger = logging.getLogger(__name__)


async def check_workflow_ownership(
    workflow_id: str,
    user: Dict[str, Any],
    client: GleitzeitClient,
    action: str = "read"
) -> Workflow:
    """
    Check if user has access to a workflow.
    
    This function checks:
    1. Admin/superuser status
    2. General permission (e.g., workflows:read)
    3. Resource ownership (user_id match)
    4. Public flag for read operations
    
    Args:
        workflow_id: The workflow ID to check
        user: Current user dict from auth
        client: Pooled client instance
        action: The action to perform (read, update, delete, etc.)
        
    Returns:
        The workflow if authorized
        
    Raises:
        HTTPException: If not authorized or workflow not found
    """
    # Get the workflow using the pooled client
    workflow = await client.get_workflow(workflow_id)
    
    if not workflow:
        raise SystemError(
            message=f"Workflow {workflow_id} not found",
            code=ErrorCode.RESOURCE_NOT_FOUND
        )
    
    # Superuser/admin always has access
    if user.get("is_superuser") or user.get("role") == "admin":
        return workflow
    
    # Get ownership info
    workflow_user_id = getattr(workflow, 'user_id', None)
    user_id = user.get('id')
    is_public = getattr(workflow, 'is_public', False)
    
    # Check ownership FIRST - owners can always access their resources
    if workflow_user_id and workflow_user_id == user_id:
        return workflow
    
    # For public workflows, allow read access
    if is_public and action in ["read", "access"]:
        return workflow
    
    # Check if user has general permission for this action
    # This is for special roles that can operate on ANY resource
    permission_name = f"workflows:{action}"
    if has_permission(user, permission_name):
        # Check if they have the "all" variant (e.g., "workflows:update:all")
        # This permission allows operating on ANY workflow, not just owned ones
        all_permission = f"workflows:{action}:all"
        if has_permission(user, all_permission):
            return workflow
        # Regular permission only allows operating on owned resources
        # Since we already checked ownership above, deny access
        pass
    
    # No access
    raise AuthorizationError(
        resource=f"workflow/{workflow_id}",
        action=action,
        reason="You don't have permission to access this workflow"
    )


async def check_task_ownership(
    task_id: str,
    user: Dict[str, Any],
    client: GleitzeitClient,
    action: str = "read"
) -> Task:
    """
    Check if user has access to a task.
    
    Tasks inherit ownership from their workflow. Standalone tasks
    check metadata for user_id.
    
    Args:
        task_id: The task ID to check
        user: Current user dict from auth
        client: Pooled client instance
        action: The action to perform
        
    Returns:
        The task if authorized
        
    Raises:
        HTTPException: If not authorized or task not found
    """
    # Get the task using the pooled client
    task = await client.get_task(task_id)
    
    if not task:
        raise SystemError(
            message=f"Task {task_id} not found",
            code=ErrorCode.RESOURCE_NOT_FOUND
        )
    
    # Superuser/admin always has access
    if user.get("is_superuser") or user.get("role") == "admin":
        return task
    
    user_id = user.get('id')
    
    # If task belongs to a workflow, check workflow ownership
    if task.workflow_id:
        try:
            # This will raise HTTPException if not authorized
            await check_workflow_ownership(
                task.workflow_id,
                user,
                client,
                action
            )
            return task
        except HTTPException:
            # Not authorized for the workflow
            raise AuthorizationError(
                resource=f"task/{task_id}",
                action=action,
                reason="You don't have permission to access this task"
            )
    else:
        # Standalone task - check metadata for user_id
        task_user_id = task.metadata.get('user_id') if task.metadata else None
        
        # If no user_id in metadata, consider it public for reads
        if not task_user_id and action in ["read", "access"]:
            return task
        
        # Check ownership
        if task_user_id == user_id:
            return task
        
        # No access
        raise AuthorizationError(
            resource=f"task/{task_id}",
            action=action,
            reason="You don't have permission to access this task"
        )


async def filter_workflows_by_ownership(
    workflows: list,
    user: Dict[str, Any],
    client: GleitzeitClient
) -> list:
    """
    Filter a list of workflows based on user ownership and permissions.
    
    Args:
        workflows: List of workflows to filter
        user: Current user dict
        client: Pooled client instance
        
    Returns:
        Filtered list of workflows user can access
    """
    # Admin/superuser sees all
    if user.get("is_superuser") or user.get("role") == "admin":
        return workflows
    
    user_id = user.get('id')
    filtered = []
    
    for workflow in workflows:
        # Check ownership - handle both object and dict types
        if hasattr(workflow, 'user_id'):
            workflow_user_id = getattr(workflow, 'user_id', None)
        elif isinstance(workflow, dict):
            workflow_user_id = workflow.get('user_id')
        else:
            workflow_user_id = None
            
        if hasattr(workflow, 'is_public'):
            is_public = getattr(workflow, 'is_public', False)
        elif isinstance(workflow, dict):
            is_public = workflow.get('is_public', False)
        else:
            is_public = False
        
        # Include if:
        # 1. Owned by user
        # 2. Public workflow
        # 3. No user_id (legacy workflows before auth was added - includes empty string)
        if workflow_user_id == user_id or is_public or workflow_user_id is None or workflow_user_id == "":
            filtered.append(workflow)
    
    return filtered


async def filter_tasks_by_ownership(
    tasks: list,
    user: Dict[str, Any],
    client: GleitzeitClient
) -> list:
    """
    Filter a list of tasks based on user ownership and permissions.
    
    Args:
        tasks: List of tasks to filter
        user: Current user dict
        client: Pooled client instance
        
    Returns:
        Filtered list of tasks user can access
    """
    # Admin/superuser sees all
    if user.get("is_superuser") or user.get("role") == "admin":
        return tasks
    
    user_id = user.get('id')
    filtered = []
    
    # Cache workflow ownership checks
    workflow_cache = {}
    
    for task in tasks:
        include = False
        
        # Get workflow_id from task
        workflow_id = getattr(task, 'workflow_id', None) if hasattr(task, 'workflow_id') else task.get('workflow_id')
        
        if workflow_id:
            # Check cached result first
            if workflow_id not in workflow_cache:
                # Check workflow ownership
                try:
                    workflow = await client.get_workflow(workflow_id)
                    if workflow:
                        workflow_user_id = getattr(workflow, 'user_id', None)
                        is_public = getattr(workflow, 'is_public', False)
                        workflow_cache[workflow_id] = (workflow_user_id == user_id or is_public)
                    else:
                        workflow_cache[workflow_id] = False
                except:
                    workflow_cache[workflow_id] = False
            
            include = workflow_cache[workflow_id]
        else:
            # Standalone task - check metadata
            metadata = getattr(task, 'metadata', {}) if hasattr(task, 'metadata') else task.get('metadata', {})
            task_user_id = metadata.get('user_id')
            
            # Include if no user_id (public) or owned by user
            include = not task_user_id or task_user_id == user_id
        
        if include:
            filtered.append(task)
    
    return filtered


def set_resource_ownership(resource: Any, user: Dict[str, Any]) -> None:
    """
    Set ownership on a resource (workflow or task).
    
    Args:
        resource: The resource to set ownership on
        user: Current user dict
    """
    user_id = user.get('id', 'anonymous')
    
    # Set user_id if the resource has this attribute
    if hasattr(resource, 'user_id'):
        resource.user_id = user_id
    
    # For tasks without workflows, set in metadata
    if hasattr(resource, 'metadata') and not getattr(resource, 'workflow_id', None):
        if resource.metadata is None:
            resource.metadata = {}
        resource.metadata['user_id'] = user_id