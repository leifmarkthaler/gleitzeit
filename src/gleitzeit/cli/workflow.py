"""
Workflow Loading and Validation - Uses centralized WorkflowLoaderV2
"""

from pathlib import Path
from typing import Dict, Any, List, Optional
from gleitzeit.core.workflow_loader_v2 import WorkflowLoaderV2
from gleitzeit.core.models import Workflow

# Create a module-level loader instance for CLI use
_loader = WorkflowLoaderV2()


def load_workflow(workflow_path: Path) -> Dict[str, Any]:
    """
    Load workflow from YAML or JSON file and return as dict.
    
    This function is kept for backward compatibility with CLI code
    that expects a dict rather than a Workflow object.
    Uses the centralized WorkflowLoaderV2 for consistency.
    """
    workflow_obj = load_workflow_as_object(workflow_path)
    return workflow_obj.model_dump()


def load_workflow_as_object(workflow_path: Path) -> Workflow:
    """
    Load workflow from file and return as Workflow object.
    
    Uses the centralized WorkflowLoaderV2 with all its validation,
    error handling, and logging capabilities.
    """
    return _loader.load_workflow_from_file(str(workflow_path))


def validate_workflow(workflow: Dict[str, Any]) -> List[str]:
    """
    Validate a workflow dictionary.
    
    Uses the centralized WorkflowLoaderV2's validation logic.
    Returns a list of error messages, empty if valid.
    """
    try:
        # Try to create a Workflow object which will trigger validation
        _loader.load_workflow_from_dict(workflow)
        return []  # No errors
    except Exception as e:
        # Extract error messages from the exception
        error_msg = str(e)
        # If it's a structured error with multiple issues, try to parse them
        if "Validation errors:" in error_msg:
            errors = error_msg.split("Validation errors:")[1].strip().split("\n")
            return [err.strip() for err in errors if err.strip()]
        else:
            return [error_msg]


def validate_workflow_file(workflow_path: Path) -> List[str]:
    """
    Validate a workflow file.
    
    Uses the centralized WorkflowLoaderV2's validation logic.
    Returns a list of error messages, empty if valid.
    """
    try:
        _loader.load_workflow_from_file(str(workflow_path))
        return []  # No errors
    except Exception as e:
        return [str(e)]