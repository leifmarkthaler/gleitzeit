"""
Signal Management for Gleitzeit.

Signal functionality is handled by:
- SignalProvider: Registers signal wait tasks
- SignalWorker: Processes signals from Redis Streams
"""

# StatelessSignalManager is deprecated - use SignalWorker instead
# from .stateless_signal_manager import StatelessSignalManager

__all__ = []