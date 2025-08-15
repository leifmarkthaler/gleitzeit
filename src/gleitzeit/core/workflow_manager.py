"""
Workflow Manager for Gleitzeit V4

High-level workflow orchestration with advanced features like parameter
substitution, conditional execution, retry policies, and workflow templates.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
import json

from gleitzeit.core.models import (
    Task, Workflow, WorkflowStatus, TaskStatus, Priority, 
    TaskResult, RetryConfig
)
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.task_queue import DependencyResolver

logger = logging.getLogger(__name__)


class WorkflowExecutionPolicy(Enum):
    """Policies for workflow execution behavior"""
    FAIL_FAST = "fail_fast"              # Stop on first task failure
    CONTINUE_ON_ERROR = "continue_on_error"  # Continue with remaining tasks
    RETRY_FAILED = "retry_failed"        # Retry failed tasks according to retry config


@dataclass
class WorkflowTemplate:
    """Template for creating workflows"""
    id: str
    name: str
    description: Optional[str]
    version: str
    tasks: List[Dict[str, Any]]  # Task templates
    parameters: Dict[str, Any] = field(default_factory=dict)  # Template parameters
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowExecution:
    """Represents a workflow execution instance"""
    execution_id: str
    workflow: Workflow
    status: WorkflowStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    task_results: Dict[str, TaskResult] = field(default_factory=dict)
    execution_context: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    policy: WorkflowExecutionPolicy = WorkflowExecutionPolicy.FAIL_FAST


class WorkflowManager:
    """
    High-level workflow orchestration and management
    
    Features:
    - Workflow templates and instantiation
    - Advanced parameter substitution and context management
    - Conditional task execution based on previous results
    - Workflow scheduling and queuing
    - Execution monitoring and progress tracking
    - Workflow persistence and recovery
    """
    
    def __init__(
        self,
        execution_engine: ExecutionEngine,
        dependency_resolver: DependencyResolver,
        template_directory: Optional[Path] = None
    ):
        self.execution_engine = execution_engine
        self.dependency_resolver = dependency_resolver
        self.template_directory = template_directory or Path("./workflow_templates")
        
        # State management
        self.active_executions: Dict[str, WorkflowExecution] = {}
        self.completed_executions: Dict[str, WorkflowExecution] = {}
        self.workflow_templates: Dict[str, WorkflowTemplate] = {}
        
        # Scheduling - event-driven with individual timers
        self.scheduled_workflows: Dict[str, Dict[str, Any]] = {}
        self._scheduler_running = False
        self._timer_tasks: Dict[str, asyncio.Task] = {}  # Track individual timer tasks
        
        # Event handlers for workflow lifecycle
        self.execution_engine.add_event_handler("task:completed", self._on_task_completed)
        self.execution_engine.add_event_handler("task:failed", self._on_task_failed)
        self.execution_engine.add_event_handler("workflow:completed", self._on_workflow_completed)
        self.execution_engine.add_event_handler("workflow:failed", self._on_workflow_failed)
        
        logger.info("Initialized WorkflowManager")
    
    async def start_scheduler(self) -> None:
        """Start the workflow scheduler"""
        if self._scheduler_running:
            return
        
        self._scheduler_running = True
        # Event-driven scheduling - use timer events instead of polling
        self._setup_event_driven_scheduler()
        logger.info("Started workflow scheduler")
    
    async def stop_scheduler(self) -> None:
        """Stop the workflow scheduler"""
        self._scheduler_running = False
        # Cancel any active timer tasks
        await self._cancel_scheduled_timers()
        logger.info("Stopped workflow scheduler")
    
    def _setup_event_driven_scheduler(self) -> None:
        """Set up event-driven scheduling using individual timers"""
        # Process any existing scheduled workflows
        for schedule_id, schedule_info in self.scheduled_workflows.items():
            self._schedule_workflow_timer(schedule_id, schedule_info)
    
    def _schedule_workflow_timer(self, schedule_id: str, schedule_info: Dict[str, Any]) -> None:
        """Schedule individual workflow using timer - no polling"""
        next_run = schedule_info.get("next_run")
        if not next_run:
            return
        
        if isinstance(next_run, str):
            next_run = datetime.fromisoformat(next_run)
        
        current_time = datetime.utcnow()
        if next_run <= current_time:
            # Schedule immediately
            task = asyncio.create_task(self._execute_scheduled_workflow(schedule_id, schedule_info))
        else:
            # Schedule for future execution
            delay = (next_run - current_time).total_seconds()
            task = asyncio.create_task(self._delayed_workflow_execution(schedule_id, schedule_info, delay))
        
        # Track the timer task
        if schedule_id in self._timer_tasks:
            self._timer_tasks[schedule_id].cancel()
        self._timer_tasks[schedule_id] = task
    
    async def _delayed_workflow_execution(self, schedule_id: str, schedule_info: Dict[str, Any], delay: float) -> None:
        """Execute workflow after delay - event-driven alternative to polling"""
        try:
            await asyncio.sleep(delay)
            if self._scheduler_running:  # Check if still running
                await self._execute_scheduled_workflow(schedule_id, schedule_info)
        except asyncio.CancelledError:
            logger.debug(f"Scheduled workflow {schedule_id} was cancelled")
        except Exception as e:
            logger.error(f"Error in delayed workflow execution {schedule_id}: {e}")
    
    async def _cancel_scheduled_timers(self) -> None:
        """Cancel all scheduled timer tasks"""
        for schedule_id, task in self._timer_tasks.items():
            task.cancel()
        
        # Wait for cancellation to complete
        if self._timer_tasks:
            await asyncio.gather(*self._timer_tasks.values(), return_exceptions=True)
        
        self._timer_tasks.clear()
    
    
    async def _execute_scheduled_workflow(self, schedule_id: str, schedule_info: Dict[str, Any]) -> None:
        """Execute a scheduled workflow - called by timer, not polling"""
        try:
            workflow_template = schedule_info["workflow_template"] 
            parameters = schedule_info.get("parameters", {})
            
            # Create workflow instance
            workflow = await self.create_workflow_from_template(
                template_id=workflow_template,
                parameters=parameters
            )
            
            # Execute workflow
            execution = await self.execute_workflow(workflow)
            logger.info(f"Executed scheduled workflow {schedule_id}: {execution.execution_id}")
            
            # Handle recurring workflows
            if "interval" in schedule_info:
                interval_seconds = schedule_info["interval"]
                next_run_time = datetime.utcnow() + timedelta(seconds=interval_seconds)
                schedule_info["next_run"] = next_run_time.isoformat()
                
                # Schedule next execution - no polling needed
                self._schedule_workflow_timer(schedule_id, schedule_info)
                logger.info(f"Scheduled next run for {schedule_id}: {next_run_time}")
            else:
                # Remove one-time scheduled workflow
                del self.scheduled_workflows[schedule_id]
                if schedule_id in self._timer_tasks:
                    del self._timer_tasks[schedule_id]
                logger.info(f"Completed one-time scheduled workflow {schedule_id}")
                
        except Exception as e:
            logger.error(f"Error executing scheduled workflow {schedule_id}: {e}")
            # Reschedule with backoff for error recovery
            if "interval" in schedule_info:
                backoff_seconds = min(schedule_info["interval"], 300)  # Max 5 min backoff
                next_run_time = datetime.utcnow() + timedelta(seconds=backoff_seconds)
                schedule_info["next_run"] = next_run_time.isoformat()
                self._schedule_workflow_timer(schedule_id, schedule_info)
    
    def load_template(self, template_path: Path) -> WorkflowTemplate:
        """Load workflow template from file"""
        with open(template_path, 'r') as f:
            template_data = json.load(f)
        
        template = WorkflowTemplate(
            id=template_data["id"],
            name=template_data["name"],
            description=template_data.get("description"),
            version=template_data["version"],
            tasks=template_data["tasks"],
            parameters=template_data.get("parameters", {}),
            metadata=template_data.get("metadata", {})
        )
        
        self.workflow_templates[template.id] = template
        logger.info(f"Loaded workflow template: {template.id}")
        return template
    
    def load_templates_from_directory(self, directory: Optional[Path] = None) -> List[WorkflowTemplate]:
        """Load all workflow templates from directory"""
        template_dir = directory or self.template_directory
        if not template_dir.exists():
            logger.warning(f"Template directory does not exist: {template_dir}")
            return []
        
        templates = []
        for template_file in template_dir.glob("*.json"):
            try:
                template = self.load_template(template_file)
                templates.append(template)
            except Exception as e:
                logger.error(f"Failed to load template from {template_file}: {e}")
        
        logger.info(f"Loaded {len(templates)} workflow templates")
        return templates
    
    async def create_workflow_from_template(
        self,
        template_id: str,
        parameters: Optional[Dict[str, Any]] = None,
        workflow_id: Optional[str] = None
    ) -> Workflow:
        """Create workflow instance from template"""
        if template_id not in self.workflow_templates:
            raise ValueError(f"Unknown template: {template_id}")
        
        template = self.workflow_templates[template_id]
        context = {**template.parameters, **(parameters or {})}
        
        # Generate workflow ID
        workflow_id = workflow_id or f"{template_id}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        # Create tasks from template
        tasks = []
        for task_template in template.tasks:
            task_data = self._substitute_template_variables(task_template, context)
            
            task = Task(
                id=task_data.get("id", f"{workflow_id}-task-{len(tasks)}"),
                name=task_data.get("name", f"Task {len(tasks) + 1}"),
                protocol=task_data["protocol"],
                method=task_data["method"],
                params=task_data.get("params", {}),
                dependencies=task_data.get("dependencies", []),
                priority=Priority(task_data.get("priority", "normal")),
                timeout=task_data.get("timeout"),
                retry_config=RetryConfig(**task_data.get("retry_config", {})) if "retry_config" in task_data else RetryConfig(),
                metadata=task_data.get("metadata", {}),
                workflow_id=workflow_id
            )
            tasks.append(task)
        
        # Create workflow
        workflow = Workflow(
            id=workflow_id,
            name=template.name,
            description=template.description,
            tasks=tasks,
            metadata={
                **template.metadata,
                "template_id": template_id,
                "template_version": template.version,
                "created_from_template": True
            }
        )
        
        logger.info(f"Created workflow {workflow_id} from template {template_id}")
        return workflow
    
    def _substitute_template_variables(self, template_data: Any, context: Dict[str, Any]) -> Any:
        """Recursively substitute template variables"""
        if isinstance(template_data, str):
            # Simple variable substitution ${var}
            import re
            pattern = r'\$\{([^}]+)\}'
            
            def replace_var(match):
                var_name = match.group(1)
                if var_name in context:
                    value = context[var_name]
                    return str(value) if not isinstance(value, str) else value
                else:
                    logger.warning(f"Template variable not found: {var_name}")
                    return match.group(0)  # Keep original if not found
            
            return re.sub(pattern, replace_var, template_data)
        
        elif isinstance(template_data, dict):
            return {k: self._substitute_template_variables(v, context) for k, v in template_data.items()}
        
        elif isinstance(template_data, list):
            return [self._substitute_template_variables(item, context) for item in template_data]
        
        else:
            return template_data
    
    def load_workflow_from_yaml(self, yaml_data: Dict[str, Any]) -> Workflow:
        """Load workflow from YAML data"""
        import yaml
        from uuid import uuid4
        
        # Parse tasks
        tasks = []
        for task_data in yaml_data.get('tasks', []):
            task = Task(
                id=task_data.get('id', f"task-{uuid4().hex[:8]}"),
                name=task_data.get('name', task_data.get('id', 'unnamed')),
                protocol=task_data.get('protocol', ''),
                method=task_data.get('method', ''),
                params=task_data.get('params', {}),
                dependencies=task_data.get('dependencies', []),
                priority=Priority.NORMAL
            )
            tasks.append(task)
        
        # Create workflow
        workflow = Workflow(
            id=yaml_data.get('id', f"workflow-{uuid4().hex[:8]}"),
            name=yaml_data.get('name', 'Unnamed Workflow'),
            description=yaml_data.get('description', ''),
            tasks=tasks,
            timeout=yaml_data.get('timeout', None)
        )
        
        return workflow
    
    async def load_workflow_from_yaml_file(self, yaml_file_path: str) -> Workflow:
        """Load workflow from YAML file"""
        import yaml
        from pathlib import Path
        
        path = Path(yaml_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {yaml_file_path}")
        
        with open(path, 'r') as f:
            yaml_data = yaml.safe_load(f)
        
        return self.load_workflow_from_yaml(yaml_data)
    
    async def execute_workflow(
        self,
        workflow: Workflow,
        policy: WorkflowExecutionPolicy = WorkflowExecutionPolicy.FAIL_FAST,
        execution_context: Optional[Dict[str, Any]] = None
    ) -> WorkflowExecution:
        """Execute a workflow with specified policy"""
        execution_id = f"{workflow.id}-exec-{datetime.utcnow().strftime('%Y%m%d-%H%M%S-%f')}"
        
        execution = WorkflowExecution(
            execution_id=execution_id,
            workflow=workflow,
            status=WorkflowStatus.PENDING,
            policy=policy,
            execution_context=execution_context or {}
        )
        
        self.active_executions[execution_id] = execution
        
        try:
            # Validate workflow
            validation_errors = self.dependency_resolver.validate_workflow_dependencies(workflow)
            if validation_errors:
                raise ValueError(f"Workflow validation failed: {'; '.join(validation_errors)}")
            
            # Set workflow status and timing
            execution.status = WorkflowStatus.RUNNING
            execution.started_at = datetime.utcnow()
            workflow.status = WorkflowStatus.RUNNING
            workflow.started_at = execution.started_at
            
            logger.info(f"Starting workflow execution {execution_id}")
            
            # Submit workflow to execution engine
            await self.execution_engine.submit_workflow(workflow)
            
            return execution
            
        except Exception as e:
            execution.status = WorkflowStatus.FAILED
            execution.completed_at = datetime.utcnow()
            workflow.status = WorkflowStatus.FAILED
            workflow.completed_at = execution.completed_at
            
            # Move to completed
            self.completed_executions[execution_id] = execution
            del self.active_executions[execution_id]
            
            logger.error(f"Workflow execution {execution_id} failed during setup: {e}")
            raise
    
    async def schedule_workflow(
        self,
        template_id: str,
        schedule_time: datetime,
        parameters: Optional[Dict[str, Any]] = None,
        recurring_interval: Optional[int] = None
    ) -> str:
        """Schedule a workflow for future execution"""
        schedule_id = f"schedule-{template_id}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        
        schedule_info = {
            "workflow_template": template_id,
            "parameters": parameters or {},
            "next_run": schedule_time.isoformat(),
            "created_at": datetime.utcnow().isoformat()
        }
        
        if recurring_interval:
            schedule_info["interval"] = recurring_interval
        
        self.scheduled_workflows[schedule_id] = schedule_info
        
        logger.info(f"Scheduled workflow {template_id} for {schedule_time.isoformat()}")
        return schedule_id
    
    async def cancel_scheduled_workflow(self, schedule_id: str) -> bool:
        """Cancel a scheduled workflow"""
        if schedule_id in self.scheduled_workflows:
            del self.scheduled_workflows[schedule_id]
            logger.info(f"Cancelled scheduled workflow {schedule_id}")
            return True
        return False
    
    async def pause_execution(self, execution_id: str) -> bool:
        """Pause a workflow execution (if supported)"""
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            execution.workflow.status = WorkflowStatus.PAUSED
            logger.info(f"Paused workflow execution {execution_id}")
            return True
        return False
    
    async def resume_execution(self, execution_id: str) -> bool:
        """Resume a paused workflow execution"""
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            if execution.workflow.status == WorkflowStatus.PAUSED:
                execution.workflow.status = WorkflowStatus.RUNNING
                logger.info(f"Resumed workflow execution {execution_id}")
                return True
        return False
    
    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel a workflow execution"""
        if execution_id in self.active_executions:
            execution = self.active_executions[execution_id]
            execution.status = WorkflowStatus.CANCELLED
            execution.workflow.status = WorkflowStatus.CANCELLED
            execution.completed_at = datetime.utcnow()
            
            # Move to completed
            self.completed_executions[execution_id] = execution
            del self.active_executions[execution_id]
            
            logger.info(f"Cancelled workflow execution {execution_id}")
            return True
        return False
    
    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a workflow execution"""
        execution = self.active_executions.get(execution_id) or self.completed_executions.get(execution_id)
        if not execution:
            return None
        
        return {
            "execution_id": execution.execution_id,
            "workflow_id": execution.workflow.id,
            "status": execution.status.value,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "total_tasks": len(execution.workflow.tasks),
            "completed_tasks": len([r for r in execution.task_results.values() if r.status == TaskStatus.COMPLETED]),
            "failed_tasks": len([r for r in execution.task_results.values() if r.status == TaskStatus.FAILED]),
            "progress": self._calculate_workflow_progress(execution),
            "retry_count": execution.retry_count
        }
    
    def _calculate_workflow_progress(self, execution: WorkflowExecution) -> float:
        """Calculate workflow execution progress (0.0 to 1.0)"""
        if not execution.workflow.tasks:
            return 1.0
        
        completed_tasks = len([r for r in execution.task_results.values() if r.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]])
        return completed_tasks / len(execution.workflow.tasks)
    
    def list_templates(self) -> List[Dict[str, Any]]:
        """List all available workflow templates"""
        return [
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "version": template.version,
                "task_count": len(template.tasks),
                "parameters": list(template.parameters.keys())
            }
            for template in self.workflow_templates.values()
        ]
    
    def list_active_executions(self) -> List[Dict[str, Any]]:
        """List all active workflow executions"""
        return [
            {
                "execution_id": execution_id,
                "workflow_id": execution.workflow.id,
                "status": execution.status.value,
                "started_at": execution.started_at.isoformat() if execution.started_at else None,
                "progress": self._calculate_workflow_progress(execution)
            }
            for execution_id, execution in self.active_executions.items()
        ]
    
    def list_scheduled_workflows(self) -> List[Dict[str, Any]]:
        """List all scheduled workflows"""
        return [
            {
                "schedule_id": schedule_id,
                "template_id": info["workflow_template"],
                "next_run": info["next_run"],
                "recurring": "interval" in info,
                "interval": info.get("interval")
            }
            for schedule_id, info in self.scheduled_workflows.items()
        ]
    
    def get_workflow_statistics(self) -> Dict[str, Any]:
        """Get comprehensive workflow statistics"""
        total_executions = len(self.active_executions) + len(self.completed_executions)
        completed_executions = len([
            e for e in self.completed_executions.values()
            if e.status == WorkflowStatus.COMPLETED
        ])
        failed_executions = len([
            e for e in self.completed_executions.values()
            if e.status == WorkflowStatus.FAILED
        ])
        
        return {
            "total_templates": len(self.workflow_templates),
            "active_executions": len(self.active_executions),
            "total_executions": total_executions,
            "completed_executions": completed_executions,
            "failed_executions": failed_executions,
            "scheduled_workflows": len(self.scheduled_workflows),
            "success_rate": (completed_executions / total_executions * 100) if total_executions > 0 else 0.0
        }
    
    # Event handlers
    async def _on_task_completed(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle task completion event"""
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            return
        
        # Find execution for this workflow
        execution = None
        for exec_id, exec_obj in self.active_executions.items():
            if exec_obj.workflow.id == workflow_id:
                execution = exec_obj
                break
        
        if execution:
            task_id = data["task_id"]
            # Get task result from execution engine
            task_result = self.execution_engine.get_task_result(task_id)
            if task_result:
                execution.task_results[task_id] = task_result
    
    async def _on_task_failed(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle task failure event"""
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            return
        
        # Find execution for this workflow
        execution = None
        for exec_id, exec_obj in self.active_executions.items():
            if exec_obj.workflow.id == workflow_id:
                execution = exec_obj
                break
        
        if execution:
            task_id = data["task_id"]
            
            # Handle based on execution policy
            if execution.policy == WorkflowExecutionPolicy.FAIL_FAST:
                # Mark workflow as failed
                execution.status = WorkflowStatus.FAILED
                execution.workflow.status = WorkflowStatus.FAILED
                execution.completed_at = datetime.utcnow()
                
                # Move to completed
                self.completed_executions[execution.execution_id] = execution
                del self.active_executions[execution.execution_id]
            
            # Store task result
            task_result = self.execution_engine.get_task_result(task_id)
            if task_result:
                execution.task_results[task_id] = task_result
    
    async def _on_workflow_completed(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle workflow completion event"""
        workflow_id = data["workflow_id"]
        
        # Find execution for this workflow
        execution = None
        execution_id = None
        for exec_id, exec_obj in self.active_executions.items():
            if exec_obj.workflow.id == workflow_id:
                execution = exec_obj
                execution_id = exec_id
                break
        
        if execution and execution_id:
            execution.status = WorkflowStatus.COMPLETED
            execution.completed_at = datetime.utcnow()
            
            # Move to completed
            self.completed_executions[execution_id] = execution
            del self.active_executions[execution_id]
            
            logger.info(f"Workflow execution {execution_id} completed")
    
    async def _on_workflow_failed(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle workflow failure event"""
        workflow_id = data["workflow_id"]
        
        # Find execution for this workflow
        execution = None
        execution_id = None
        for exec_id, exec_obj in self.active_executions.items():
            if exec_obj.workflow.id == workflow_id:
                execution = exec_obj
                execution_id = exec_id
                break
        
        if execution and execution_id:
            execution.status = WorkflowStatus.FAILED
            execution.completed_at = datetime.utcnow()
            
            # Move to completed
            self.completed_executions[execution_id] = execution
            del self.active_executions[execution_id]
            
            logger.info(f"Workflow execution {execution_id} failed")