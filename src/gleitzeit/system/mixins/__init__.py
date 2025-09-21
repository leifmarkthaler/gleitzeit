"""
System manager mixins for modular streaming-only architecture.

These mixins provide specific functionality that can be composed together
to create a complete streaming system manager without inheritance complexity.

IMPORTANT: Only stateless mixins are used. The old loop-based mixins are deprecated.
"""

from .base import BaseSystemMixin
# Stateless mixins (the ONLY ones to use)
from .stateless_stream_core import StatelessStreamCoreMixin
from .stateless_stream_timers import StatelessStreamTimersMixin
from .stateless_stream_signals import StatelessStreamSignalsMixin
# Regular mixins still in use
from .stream_execution import StreamExecutionMixin
from .stream_monitoring import StreamMonitoringMixin
from .stream_providers import StreamProvidersMixin
from .stream_auth import StreamAuthMixin

__all__ = [
    'BaseSystemMixin',
    # Stateless mixins
    'StatelessStreamCoreMixin',
    'StatelessStreamTimersMixin',
    'StatelessStreamSignalsMixin',
    # Regular mixins
    'StreamExecutionMixin',
    'StreamMonitoringMixin',
    'StreamProvidersMixin',
    'StreamAuthMixin'
]