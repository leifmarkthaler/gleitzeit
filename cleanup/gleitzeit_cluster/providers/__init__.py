"""
External Provider Integrations

This package contains integrations with external AI/LLM providers for the unified Socket.IO architecture.
"""

from .openai_client import OpenAIClient, OpenAIConfig, OpenAIError

__all__ = [
    'OpenAIClient',
    'OpenAIConfig', 
    'OpenAIError'
]