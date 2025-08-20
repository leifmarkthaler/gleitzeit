"""
Protocol definitions for Gleitzeit V4
"""

from gleitzeit.protocols.llm_protocol import LLM_PROTOCOL_V1
from gleitzeit.protocols.python_protocol import PYTHON_PROTOCOL_V1
from gleitzeit.protocols.mcp_protocol import mcp_protocol as MCP_PROTOCOL_V1

__all__ = ["LLM_PROTOCOL_V1", "PYTHON_PROTOCOL_V1", "MCP_PROTOCOL_V1"]
