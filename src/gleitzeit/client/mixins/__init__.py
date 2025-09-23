"""
Gleitzeit client mixins for modular functionality.

Each mixin provides a specific set of functionality that can be
composed together to create the full client.
"""

from .auth import AuthMixin, AuthenticationError, AuthorizationError
from .retry import RetryMixin
from .workflows import WorkflowMixin, WorkflowResponse, WorkflowStatus
from .tasks import TaskMixin, TaskStatus
from .monitoring import MonitoringMixin, SystemHealth, WorkerStatus

__all__ = [
    # Auth
    'AuthMixin',
    'AuthenticationError',
    'AuthorizationError',

    # Retry
    'RetryMixin',

    # Workflows
    'WorkflowMixin',
    'WorkflowResponse',
    'WorkflowStatus',

    # Tasks
    'TaskMixin',
    'TaskStatus',

    # Monitoring
    'MonitoringMixin',
    'SystemHealth',
    'WorkerStatus',
]