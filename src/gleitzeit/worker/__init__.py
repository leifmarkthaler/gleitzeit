"""
Gleitzeit Worker Service

Standalone worker service that runs ClientPool for distributed execution.
"""

from .service import WorkerService
from .config import WorkerConfig

__all__ = [
    'WorkerService',
    'WorkerConfig'
]