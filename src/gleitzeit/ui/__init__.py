"""
Gleitzeit Web UI Package

A modern web interface for monitoring and managing Gleitzeit workflows.
"""

__version__ = "0.1.0"

# Export main app for convenience
try:
    from .api.app import app
except ImportError:
    app = None
    
__all__ = ["app"]