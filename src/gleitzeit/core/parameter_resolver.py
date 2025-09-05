"""
Parameter Resolution Service for Gleitzeit

Extracted from ExecutionEngine to provide shared parameter substitution
functionality across all components.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from gleitzeit.persistence.base import PersistenceBackend
from gleitzeit.core.models import Task

logger = logging.getLogger(__name__)


class ParameterResolver:
    """
    Shared service for resolving parameter references in task parameters.
    
    Supports:
    - ${task-id.field} references between tasks
    - ${task-name.field} references using task names
    - Nested field navigation (e.g., ${task1.result.data.value})
    - Recursive substitution through dicts and lists
    """
    
    def __init__(self, persistence: PersistenceBackend):
        """
        Initialize ParameterResolver with persistence backend.
        
        Args:
            persistence: Backend for retrieving task results
        """
        self.persistence = persistence
        self.task_name_to_id_map: Dict[str, str] = {}
        
    def set_task_name_mapping(self, mapping: Dict[str, str]) -> None:
        """
        Set mapping from task names to task IDs for name-based references.
        
        Args:
            mapping: Dictionary mapping task names to their IDs
        """
        self.task_name_to_id_map = mapping
        logger.debug(f"Updated task name mapping with {len(mapping)} entries")
        
    async def resolve_parameters(
        self,
        task: Task,
        task_name_mapping: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Resolve parameter references in task parameters.
        
        Args:
            task: Task whose parameters need resolution
            task_name_mapping: Optional mapping of task names to IDs
            
        Returns:
            Resolved parameters with all references substituted
        """
        if task_name_mapping:
            self.set_task_name_mapping(task_name_mapping)
            
        logger.info(f"Resolving parameters for task {task.id} ({task.name})")
        logger.debug(f"Original params: {task.params}")
        
        resolved = await self._substitute_parameters(task.params.copy())
        
        logger.info(f"Resolved params for {task.name}: {resolved}")
        return resolved
        
    async def _substitute_parameters(self, obj: Any) -> Any:
        """
        Recursively substitute parameter references in an object.
        
        Args:
            obj: Object to process (str, dict, list, or other)
            
        Returns:
            Object with all parameter references resolved
        """
        if isinstance(obj, str):
            return await self._substitute_string_parameters(obj)
        elif isinstance(obj, dict):
            return {k: await self._substitute_parameters(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [await self._substitute_parameters(item) for item in obj]
        else:
            return obj
            
    async def _substitute_string_parameters(self, text: str) -> Any:
        """
        Substitute parameter references in a string.
        
        Args:
            text: String that may contain ${...} references
            
        Returns:
            Resolved value (may be string or actual referenced object)
        """
        # Pattern for ${task-id.field} references
        pattern = r'\$\{([^}]+)\}'
        matches = re.findall(pattern, text)
        
        if not matches:
            return text
            
        for match in matches:
            ref_value = await self._resolve_reference(match)
            
            if ref_value is not None:
                # If entire string is just the reference, return actual value
                if text == f"${{{match}}}":
                    logger.info(f"Parameter substitution: ${{{match}}} -> {ref_value}")
                    return ref_value
                # Otherwise, do string replacement
                else:
                    replacement = str(ref_value) if not isinstance(ref_value, str) else ref_value
                    logger.info(f"Parameter substitution in string: ${{{match}}} -> {replacement}")
                    text = text.replace(f"${{{match}}}", replacement)
                    
        return text
        
    async def _resolve_reference(self, reference: str) -> Any:
        """
        Resolve a single parameter reference.
        
        Args:
            reference: Reference string (e.g., "task1.result.data")
            
        Returns:
            Resolved value or None if not found
        """
        parts = reference.split('.')
        ref_task_id = parts[0]
        field_path = parts[1:] if len(parts) > 1 else ['result']
        
        # Resolve task name to ID if needed
        actual_task_id = self._resolve_task_id(ref_task_id)
        
        # Get task result from persistence
        ref_result = await self.persistence.get_task_result(actual_task_id)
        
        if not ref_result:
            logger.warning(f"Referenced task {actual_task_id} not found in results")
            return None
            
        # Navigate through field path
        return self._navigate_field_path(ref_result, field_path, actual_task_id)
        
    def _resolve_task_id(self, ref_task_id: str) -> str:
        """
        Resolve task name to task ID if mapping exists.
        
        Args:
            ref_task_id: Task ID or name
            
        Returns:
            Actual task ID
        """
        if ref_task_id in self.task_name_to_id_map:
            actual_id = self.task_name_to_id_map[ref_task_id]
            logger.debug(f"Resolved task name '{ref_task_id}' to ID '{actual_id}'")
            return actual_id
        return ref_task_id
        
    def _navigate_field_path(
        self,
        ref_result: Any,
        field_path: List[str],
        task_id: str
    ) -> Any:
        """
        Navigate through nested fields to get the referenced value.
        
        Args:
            ref_result: Task result object
            field_path: List of field names to navigate
            task_id: Task ID for logging
            
        Returns:
            Value at the field path or None if not found
        """
        # If field_path is just ['result'] and ref_result has a result attribute,
        # return that directly
        if field_path == ['result'] and hasattr(ref_result, 'result'):
            return ref_result.result
            
        # Start with result field if it exists and not explicitly navigating to it
        ref_value = ref_result.result if hasattr(ref_result, 'result') else ref_result
        
        for field in field_path:
            # Skip 'result' if we already extracted it above
            if field == 'result' and hasattr(ref_result, 'result'):
                continue
                
            if isinstance(ref_value, dict) and field in ref_value:
                ref_value = ref_value[field]
            elif hasattr(ref_value, field):
                ref_value = getattr(ref_value, field)
            else:
                logger.warning(f"Field {field} not found in task {task_id} result")
                if isinstance(ref_value, dict):
                    logger.warning(f"  Available fields: {list(ref_value.keys())}")
                logger.warning(f"  ref_value type: {type(ref_value)}")
                return None
                
        return ref_value
        
    async def resolve_workflow_parameters(
        self,
        tasks: List[Task],
        completed_tasks: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Resolve parameters for multiple tasks in a workflow.
        
        Args:
            tasks: List of tasks to resolve parameters for
            completed_tasks: Already completed tasks with their results
            
        Returns:
            Dictionary mapping task IDs to resolved parameters
        """
        # Build task name mapping
        name_mapping = {task.name: task.id for task in tasks}
        self.set_task_name_mapping(name_mapping)
        
        resolved_params = {}
        
        for task in tasks:
            # Only resolve if task has dependencies
            if task.dependencies:
                resolved_params[task.id] = await self.resolve_parameters(task)
            else:
                resolved_params[task.id] = task.params
                
        return resolved_params