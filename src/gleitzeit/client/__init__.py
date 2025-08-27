"""
Modular Gleitzeit client package.

Provides a backward-compatible interface while using the new modular architecture.
"""

import warnings
from typing import Union
from .base import ModularGleitzeitClient, ClientMode


class GleitzeitClient(ModularGleitzeitClient):
    """
    Backward-compatible Gleitzeit client.
    
    This is a facade that provides compatibility with the old monolithic client
    while using the new modular architecture under the hood.
    """
    
    def __init__(self, *args, use_legacy: bool = False, **kwargs):
        """
        Initialize Gleitzeit client.
        
        Args:
            use_legacy: If True, use the old monolithic client (deprecated)
            *args, **kwargs: Arguments passed to ModularGleitzeitClient
        """
        if use_legacy:
            warnings.warn(
                "Legacy client mode is deprecated and will be removed in v1.0. "
                "Please migrate to the new modular client.",
                DeprecationWarning,
                stacklevel=2
            )
            # Import and use legacy client
            from gleitzeit.client_legacy import GleitzeitClient as LegacyClient
            self.__class__ = LegacyClient
            LegacyClient.__init__(self, *args, **kwargs)
        else:
            # Use new modular client
            super().__init__(*args, **kwargs)


# Export main components
__all__ = [
    'GleitzeitClient',
    'ModularGleitzeitClient',
    'ClientMode'
]