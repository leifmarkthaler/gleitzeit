"""
Gleitzeit client adapters for different modes (API, Native).
"""

from .base import BaseAdapter
from .api import APIAdapter
from .native import NativeAdapter

__all__ = ['BaseAdapter', 'APIAdapter', 'NativeAdapter']