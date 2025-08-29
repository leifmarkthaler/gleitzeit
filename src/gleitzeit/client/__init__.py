"""
Modular Gleitzeit client package.

The new modular architecture for the Gleitzeit client.
"""

from .base import ModularGleitzeitClient, ClientMode


class GleitzeitClient(ModularGleitzeitClient):
    """
    Gleitzeit client using the modular architecture.
    
    This client provides a clean, modular design with separate modules
    for different functionality (tasks, workflows, resources, etc.).
    """
    
    def __init__(self, *args, **kwargs):
        """
        Initialize Gleitzeit client.
        
        Args:
            *args, **kwargs: Arguments passed to ModularGleitzeitClient
        """
        # Use new modular client
        super().__init__(*args, **kwargs)


# Export main components
__all__ = [
    'GleitzeitClient',
    'ModularGleitzeitClient',
    'ClientMode'
]