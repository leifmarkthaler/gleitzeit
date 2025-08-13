"""
MCP Provider module entry point
"""

from .mcp_provider import main
import asyncio

if __name__ == '__main__':
    asyncio.run(main())