"""
Factory for creating models with centralized error handling.

This module provides factory functions that wrap Pydantic validation
errors in the centralized Gleitzeit error system.
"""

from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from .models import Task, Workflow, WorkflowExecution
from .errors import TaskValidationError, WorkflowValidationError


class TaskFactory:
    """Factory for creating Task instances with centralized error handling."""
    
    @staticmethod
    def create(**kwargs) -> Task:
        """
        Create a Task instance with validation error wrapping.
        
        Args:
            **kwargs: Task fields
            
        Returns:
            Task instance
            
        Raises:
            TaskValidationError: If validation fails
        """
        try:
            return Task(**kwargs)
        except ValidationError as e:
            # Extract validation errors from Pydantic
            errors = []
            for error in e.errors():
                field = '.'.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                errors.append(f"{field}: {msg}")
            
            # Wrap in centralized error
            task_id = kwargs.get('id', 'unknown')
            raise TaskValidationError(
                task_id=task_id,
                validation_errors=errors
            ) from e
    
    @staticmethod
    def create_with_defaults(
        id: str,
        protocol: str,
        config: Dict[str, Any],
        name: Optional[str] = None,
        method: Optional[str] = None,
        **kwargs
    ) -> Task:
        """
        Create a Task with sensible defaults.
        
        Args:
            id: Task ID
            protocol: Protocol to use
            config: Task configuration
            name: Task name (defaults to id)
            method: Method name (defaults to 'execute')
            **kwargs: Additional fields
            
        Returns:
            Task instance
            
        Raises:
            TaskValidationError: If validation fails
        """
        # Apply defaults
        if name is None:
            name = id
        if method is None:
            method = 'execute'
        
        # Merge all fields
        fields = {
            'id': id,
            'name': name,
            'method': method,
            'protocol': protocol,
            'config': config,
            **kwargs
        }
        
        return TaskFactory.create(**fields)


class WorkflowFactory:
    """Factory for creating Workflow instances with centralized error handling."""
    
    @staticmethod
    def create(**kwargs) -> Workflow:
        """
        Create a Workflow instance with validation error wrapping.
        
        Args:
            **kwargs: Workflow fields
            
        Returns:
            Workflow instance
            
        Raises:
            WorkflowValidationError: If validation fails
        """
        try:
            return Workflow(**kwargs)
        except ValidationError as e:
            # Extract validation errors from Pydantic
            errors = []
            for error in e.errors():
                field = '.'.join(str(loc) for loc in error['loc'])
                msg = error['msg']
                errors.append(f"{field}: {msg}")
            
            # Wrap in centralized error
            workflow_id = kwargs.get('id', 'unknown')
            raise WorkflowValidationError(
                workflow_id=workflow_id,
                validation_errors=errors
            ) from e
    
    @staticmethod
    def create_with_defaults(
        id: str,
        tasks: List[Task],
        name: Optional[str] = None,
        description: Optional[str] = None,
        **kwargs
    ) -> Workflow:
        """
        Create a Workflow with sensible defaults.
        
        Args:
            id: Workflow ID
            tasks: List of tasks
            name: Workflow name (defaults to id)
            description: Workflow description
            **kwargs: Additional fields
            
        Returns:
            Workflow instance
            
        Raises:
            WorkflowValidationError: If validation fails
        """
        # Apply defaults
        if name is None:
            name = id
        
        # Merge all fields
        fields = {
            'id': id,
            'name': name,
            'tasks': tasks,
            **kwargs
        }
        
        if description is not None:
            fields['description'] = description
        
        return WorkflowFactory.create(**fields)