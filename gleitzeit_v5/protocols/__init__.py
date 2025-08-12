"""
Gleitzeit V5 Protocol Specifications

Standard protocol definitions for various provider types.
"""

from .llm_protocol import LLM_PROTOCOL_V1
from .python_protocol import PYTHON_PROTOCOL_V1

__all__ = [
    'LLM_PROTOCOL_V1',
    'PYTHON_PROTOCOL_V1'
]