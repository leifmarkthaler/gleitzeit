"""
Gleitzeit Extension Manager

Separate package for managing Gleitzeit extensions, keeping the core library clean
while providing powerful extensibility for LLM providers and other integrations.

Usage:
    # Minimal - core only
    from gleitzeit_cluster import GleitzeitCluster
    cluster = GleitzeitCluster()
    
    # With extensions
    from gleitzeit_cluster import GleitzeitCluster
    from gleitzeit_extensions import ExtensionManager
    
    cluster = GleitzeitCluster()
    extensions = ExtensionManager()
    extensions.attach_to_cluster(cluster)
    
    extensions.load("openai", api_key="...")
    await cluster.start()
    
    # Helper function
    from gleitzeit_extensions import create_cluster_with_extensions
    cluster = create_cluster_with_extensions(["openai"], openai_api_key="...")
"""

from .manager import ExtensionManager
from .decorators import extension, requires, model, capability
from .helpers import create_cluster_with_extensions
from .exceptions import ExtensionError, ExtensionNotFound, ExtensionConfigError

__version__ = "1.0.0"
__all__ = [
    'ExtensionManager',
    'extension',
    'requires', 
    'model',
    'capability',
    'create_cluster_with_extensions',
    'ExtensionError',
    'ExtensionNotFound',
    'ExtensionConfigError'
]