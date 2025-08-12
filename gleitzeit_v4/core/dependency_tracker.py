"""
Dependency Resolution Tracker for Gleitzeit V4

Provides idempotent task submission and dependency resolution tracking
to prevent duplicate task submissions and handle race conditions.
"""

import asyncio
import logging
from typing import Set, Dict, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ResolutionAttempt:
    """Track resolution attempts for a workflow"""
    workflow_id: str
    attempt_count: int = 0
    last_attempt: Optional[datetime] = None
    submitted_tasks: Set[str] = field(default_factory=set)
    failed_attempts: List[str] = field(default_factory=list)


class DependencyTracker:
    """
    Track dependency resolution and task submissions to ensure idempotency
    
    Features:
    - Prevents duplicate task submissions
    - Tracks resolution attempts per workflow
    - Provides deduplication for concurrent resolution requests
    - Maintains submission history for debugging
    """
    
    def __init__(self, max_attempts: int = 3, attempt_timeout: int = 300):
        """
        Initialize the dependency tracker
        
        Args:
            max_attempts: Maximum resolution attempts per workflow
            attempt_timeout: Timeout in seconds before allowing retry
        """
        self.submitted_tasks: Set[str] = set()
        self.resolution_attempts: Dict[str, ResolutionAttempt] = {}
        self.pending_resolutions: Set[str] = set()
        self.max_attempts = max_attempts
        self.attempt_timeout = attempt_timeout
        self._lock = asyncio.Lock()
        
        # Track submission history for debugging
        self.submission_history: List[Dict] = []
        
        logger.info(f"Initialized DependencyTracker with max_attempts={max_attempts}")
    
    async def mark_task_submitted(self, task_id: str, workflow_id: Optional[str] = None) -> bool:
        """
        Mark a task as submitted (idempotent operation)
        
        Args:
            task_id: Task identifier
            workflow_id: Optional workflow identifier
            
        Returns:
            True if task was newly submitted, False if already submitted
        """
        async with self._lock:
            if task_id in self.submitted_tasks:
                logger.debug(f"Task {task_id} already submitted, skipping")
                return False
            
            self.submitted_tasks.add(task_id)
            
            # Track in workflow attempts if workflow_id provided
            if workflow_id and workflow_id in self.resolution_attempts:
                self.resolution_attempts[workflow_id].submitted_tasks.add(task_id)
            
            # Add to history
            self.submission_history.append({
                "task_id": task_id,
                "workflow_id": workflow_id,
                "timestamp": datetime.utcnow(),
                "action": "submitted"
            })
            
            logger.info(f"Task {task_id} marked as submitted")
            return True
    
    async def is_task_submitted(self, task_id: str) -> bool:
        """Check if a task has been submitted"""
        async with self._lock:
            return task_id in self.submitted_tasks
    
    async def should_resolve_workflow(self, workflow_id: str) -> bool:
        """
        Check if we should attempt dependency resolution for a workflow
        
        Implements backoff and deduplication logic
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            True if resolution should proceed, False otherwise
        """
        async with self._lock:
            # Check if resolution is already in progress
            if workflow_id in self.pending_resolutions:
                logger.debug(f"Resolution already pending for workflow {workflow_id}")
                return False
            
            # Check resolution attempts
            if workflow_id not in self.resolution_attempts:
                self.resolution_attempts[workflow_id] = ResolutionAttempt(workflow_id)
            
            attempt = self.resolution_attempts[workflow_id]
            
            # Check max attempts
            if attempt.attempt_count >= self.max_attempts:
                logger.warning(f"Max resolution attempts reached for workflow {workflow_id}")
                return False
            
            # Check timeout since last attempt (exponential backoff)
            if attempt.last_attempt:
                backoff_seconds = min(2 ** attempt.attempt_count, self.attempt_timeout)
                time_since_last = (datetime.utcnow() - attempt.last_attempt).total_seconds()
                
                if time_since_last < backoff_seconds:
                    logger.debug(
                        f"Workflow {workflow_id} in backoff period "
                        f"({time_since_last:.1f}s < {backoff_seconds}s)"
                    )
                    return False
            
            # Mark as pending
            self.pending_resolutions.add(workflow_id)
            attempt.attempt_count += 1
            attempt.last_attempt = datetime.utcnow()
            
            logger.info(f"Allowing resolution attempt {attempt.attempt_count} for workflow {workflow_id}")
            return True
    
    async def complete_resolution(self, workflow_id: str, success: bool = True, error: Optional[str] = None):
        """
        Mark a resolution attempt as complete
        
        Args:
            workflow_id: Workflow identifier
            success: Whether resolution was successful
            error: Optional error message if failed
        """
        async with self._lock:
            # Remove from pending
            self.pending_resolutions.discard(workflow_id)
            
            if workflow_id in self.resolution_attempts:
                attempt = self.resolution_attempts[workflow_id]
                
                if not success:
                    attempt.failed_attempts.append(
                        f"{datetime.utcnow().isoformat()}: {error or 'Unknown error'}"
                    )
                    logger.error(f"Resolution failed for workflow {workflow_id}: {error}")
                else:
                    # Reset attempt count on success
                    attempt.attempt_count = 0
                    logger.info(f"Resolution successful for workflow {workflow_id}")
    
    async def reset_workflow(self, workflow_id: str):
        """
        Reset tracking for a workflow (used when workflow is restarted)
        
        Args:
            workflow_id: Workflow identifier
        """
        async with self._lock:
            if workflow_id in self.resolution_attempts:
                # Remove submitted tasks from global set
                for task_id in self.resolution_attempts[workflow_id].submitted_tasks:
                    self.submitted_tasks.discard(task_id)
                
                # Remove workflow tracking
                del self.resolution_attempts[workflow_id]
            
            self.pending_resolutions.discard(workflow_id)
            
            logger.info(f"Reset tracking for workflow {workflow_id}")
    
    async def cleanup_completed_workflows(self, completed_workflow_ids: List[str]):
        """
        Clean up tracking for completed workflows to free memory
        
        Args:
            completed_workflow_ids: List of completed workflow IDs
        """
        async with self._lock:
            for workflow_id in completed_workflow_ids:
                if workflow_id in self.resolution_attempts:
                    attempt = self.resolution_attempts[workflow_id]
                    
                    # Keep submitted tasks in global set (they're done)
                    # but remove workflow-specific tracking
                    del self.resolution_attempts[workflow_id]
                
                self.pending_resolutions.discard(workflow_id)
            
            logger.info(f"Cleaned up tracking for {len(completed_workflow_ids)} completed workflows")
    
    def get_stats(self) -> Dict:
        """Get tracker statistics for monitoring"""
        return {
            "total_submitted_tasks": len(self.submitted_tasks),
            "tracked_workflows": len(self.resolution_attempts),
            "pending_resolutions": len(self.pending_resolutions),
            "recent_submissions": len([
                h for h in self.submission_history[-100:]  # Last 100
                if (datetime.utcnow() - h["timestamp"]).total_seconds() < 300
            ]),
            "failed_resolutions": sum(
                len(attempt.failed_attempts) 
                for attempt in self.resolution_attempts.values()
            )
        }
    
    async def get_workflow_status(self, workflow_id: str) -> Optional[Dict]:
        """
        Get detailed status for a specific workflow
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Dictionary with workflow tracking details or None
        """
        async with self._lock:
            if workflow_id not in self.resolution_attempts:
                return None
            
            attempt = self.resolution_attempts[workflow_id]
            return {
                "workflow_id": workflow_id,
                "attempt_count": attempt.attempt_count,
                "last_attempt": attempt.last_attempt.isoformat() if attempt.last_attempt else None,
                "submitted_tasks": list(attempt.submitted_tasks),
                "failed_attempts": attempt.failed_attempts[-5:],  # Last 5 failures
                "is_pending": workflow_id in self.pending_resolutions
            }