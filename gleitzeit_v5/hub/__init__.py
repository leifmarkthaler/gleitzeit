"""
Central Event Hub for Gleitzeit

The central event hub acts as a pure event router and coordinator,
managing connections from distributed components and routing events
between them based on component capabilities and system state.
"""

from .central_hub import CentralHub

__all__ = ["CentralHub"]