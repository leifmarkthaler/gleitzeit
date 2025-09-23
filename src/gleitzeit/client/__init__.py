"""
Gleitzeit Python Client SDK with modular architecture.

The client provides a modular mixin-based architecture for interacting
with the Gleitzeit API, supporting authentication, workflow management,
task operations, and system monitoring.
"""

from .client import GleitzeitClient
from .mixins import (
    AuthenticationError,
    AuthorizationError,
    WorkflowResponse,
    WorkflowStatus,
    TaskStatus,
    SystemHealth,
    WorkerStatus
)

__all__ = [
    # Main client
    'GleitzeitClient',

    # Exceptions
    'AuthenticationError',
    'AuthorizationError',

    # Data classes
    'WorkflowResponse',
    'WorkflowStatus',
    'TaskStatus',
    'SystemHealth',
    'WorkerStatus',
]

# Version
__version__ = '0.0.7'