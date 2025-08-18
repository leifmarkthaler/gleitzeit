"""
Experimental Instructor integration for Gleitzeit

Provides structured output capabilities using Instructor library
for validated, typed responses from LLMs.
"""

from .provider import InstructorProvider
from .models import StructuredOutput, SchemaDefinition

__all__ = [
    'InstructorProvider',
    'StructuredOutput',
    'SchemaDefinition',
]