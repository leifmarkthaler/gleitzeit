"""
Instructor Provider for structured LLM outputs

Integrates the Instructor library to provide validated, typed responses
from LLMs using Pydantic models.
"""

import logging
from typing import Dict, Any, List, Optional, Type, Union
import os
import json
from enum import Enum

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core.errors import (
    InvalidParameterError, 
    TaskExecutionError,
    ProviderError
)

from .models import StructuredOutput, SchemaDefinition

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    COHERE = "cohere"
    MISTRAL = "mistral"
    LITELLM = "litellm"  # For Ollama and other OpenAI-compatible APIs


class InstructorProvider(ProtocolProvider):
    """
    Provider for structured LLM outputs using Instructor
    
    This provider uses the Instructor library to ensure LLM outputs
    conform to specified Pydantic schemas, with automatic retries
    on validation failures.
    
    Methods:
    - llm/structured: Generate structured output with schema validation
    - llm/extract: Extract structured data from text
    - llm/classify: Classify text into predefined categories
    """
    
    def __init__(
        self,
        provider_id: str = "instructor",
        protocol_id: str = "llm/structured",
        default_provider: str = "openai",
        default_model: Optional[str] = None,
        max_retries: int = 3,
        **kwargs
    ):
        """
        Initialize Instructor provider
        
        Args:
            provider_id: Unique provider identifier
            protocol_id: Protocol this provider implements
            default_provider: Default LLM provider to use
            default_model: Default model for the provider
            max_retries: Maximum validation retry attempts
        """
        super().__init__(
            provider_id=provider_id,
            protocol_id=protocol_id,
            name="Instructor Provider",
            description="Provides structured, validated LLM outputs using Instructor"
        )
        
        self.default_provider = default_provider
        self.default_model = default_model or self._get_default_model(default_provider)
        self.max_retries = max_retries
        self.clients: Dict[str, Any] = {}
        
    def _get_default_model(self, provider: str) -> str:
        """Get default model for provider"""
        defaults = {
            "openai": "gpt-4-turbo-preview",
            "anthropic": "claude-3-opus-20240229",
            "cohere": "command-r",
            "mistral": "mistral-large-latest",
            "litellm": "gpt-3.5-turbo"
        }
        return defaults.get(provider, "gpt-3.5-turbo")
    
    async def initialize(self) -> None:
        """Initialize the provider and check for required libraries"""
        try:
            import instructor
            self.instructor = instructor
            version = getattr(instructor, '__version__', 'unknown')
            logger.info(f"Initialized {self.name} with Instructor v{version}")
        except ImportError:
            raise ProviderError(
                "Instructor library not installed. Run: pip install instructor"
            )
        
        # Check for API keys
        self._check_api_keys()
    
    def _check_api_keys(self) -> None:
        """Check for required API keys based on providers"""
        key_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "cohere": "COHERE_API_KEY",
            "mistral": "MISTRAL_API_KEY"
        }
        
        for provider, env_var in key_map.items():
            if not os.getenv(env_var):
                logger.warning(f"No {env_var} found for {provider} provider")
    
    async def cleanup(self) -> None:
        """Clean up resources"""
        self.clients.clear()
        logger.info(f"Cleaned up {self.name}")
    
    async def shutdown(self) -> None:
        """Shutdown the provider"""
        await self.cleanup()
    
    async def health_check(self) -> bool:
        """Check if provider is healthy"""
        try:
            import instructor
            return True
        except ImportError:
            return False
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported methods"""
        return [
            "llm/structured",
            "llm/extract", 
            "llm/classify",
            "structured/generate",  # Alias
            "structured/extract",   # Alias
        ]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a request"""
        return await self.execute(method, params)
    
    def can_handle(self, method: str) -> bool:
        """Check if this provider can handle a method"""
        return method in self.get_supported_methods()
    
    async def execute(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a structured LLM method
        
        Args:
            method: Method to execute
            params: Method parameters including schema and messages
            
        Returns:
            Structured output result
        """
        # Route to appropriate handler
        if method in ["llm/structured", "structured/generate"]:
            return await self._structured_generate(params)
        elif method in ["llm/extract", "structured/extract"]:
            return await self._extract_data(params)
        elif method == "llm/classify":
            return await self._classify_text(params)
        else:
            raise InvalidParameterError("method", f"Unsupported method: {method}")
    
    async def _structured_generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate structured output with schema validation
        
        Parameters:
            - schema: Dict or Pydantic model definition
            - messages: List of chat messages
            - provider: LLM provider (optional, uses default)
            - model: Model name (optional, uses default for provider)
            - max_retries: Max validation retries (optional)
        """
        # Extract parameters
        schema = params.get('schema')
        messages = params.get('messages', [])
        provider = params.get('provider', self.default_provider)
        model = params.get('model', self.default_model)
        max_retries = params.get('max_retries', self.max_retries)
        
        if not schema:
            raise InvalidParameterError("schema", "Schema is required for structured generation")
        if not messages:
            raise InvalidParameterError("messages", "Messages are required for structured generation")
        
        try:
            # Get or create client
            client = await self._get_client(provider)
            
            # Convert schema to Pydantic model if needed
            if isinstance(schema, dict):
                schema_def = SchemaDefinition.from_dict(schema)
                pydantic_model = schema_def.to_pydantic_model()
            else:
                # Assume it's already a Pydantic model class
                pydantic_model = schema
            
            # Use Instructor to get structured output
            import asyncio
            
            # Run synchronous Instructor call in executor
            # (Instructor doesn't have full async support yet)
            loop = asyncio.get_event_loop()
            
            def _sync_call():
                if provider == "openai":
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_model=pydantic_model,
                        max_retries=max_retries
                    )
                elif provider == "anthropic":
                    # Convert messages format for Anthropic
                    anthropic_messages = self._convert_to_anthropic_format(messages)
                    response = client.messages.create(
                        model=model,
                        messages=anthropic_messages,
                        response_model=pydantic_model,
                        max_retries=max_retries,
                        max_tokens=4096
                    )
                else:
                    # Generic OpenAI-compatible format
                    response = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        response_model=pydantic_model,
                        max_retries=max_retries
                    )
                return response
            
            response = await loop.run_in_executor(None, _sync_call)
            
            # Convert response to dict
            if hasattr(response, 'model_dump'):
                data = response.model_dump()
            elif hasattr(response, 'dict'):
                data = response.dict()
            else:
                data = dict(response)
            
            return {
                "success": True,
                "data": data,
                "model": model,
                "provider": provider,
                "validation_attempts": 1  # TODO: Get actual retry count from Instructor
            }
            
        except Exception as e:
            logger.error(f"Structured generation failed: {e}")
            raise TaskExecutionError(f"Failed to generate structured output: {str(e)}")
    
    async def _extract_data(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract structured data from text
        
        Parameters:
            - text: Text to extract from
            - schema: Extraction schema
            - provider: LLM provider (optional)
            - model: Model name (optional)
        """
        text = params.get('text', '')
        schema = params.get('schema')
        
        if not text:
            raise InvalidParameterError("text", "Text is required for extraction")
        if not schema:
            raise InvalidParameterError("schema", "Schema is required for extraction")
        
        # Convert to chat format for structured generation
        messages = [
            {"role": "system", "content": "Extract the requested information from the provided text."},
            {"role": "user", "content": text}
        ]
        
        params['messages'] = messages
        return await self._structured_generate(params)
    
    async def _classify_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Classify text into categories
        
        Parameters:
            - text: Text to classify
            - categories: List of categories or enum schema
            - provider: LLM provider (optional)
            - model: Model name (optional)
        """
        text = params.get('text', '')
        categories = params.get('categories', [])
        
        if not text:
            raise InvalidParameterError("text", "Text is required for classification")
        if not categories:
            raise InvalidParameterError("categories", "Categories are required for classification")
        
        # Create classification schema
        from enum import Enum
        ClassificationEnum = Enum('Classification', {cat: cat for cat in categories})
        
        from pydantic import BaseModel
        class ClassificationResult(BaseModel):
            category: ClassificationEnum
            confidence: Optional[float] = None
            reasoning: Optional[str] = None
        
        # Convert to structured generation format
        messages = [
            {"role": "system", "content": f"Classify the following text into one of these categories: {', '.join(categories)}"},
            {"role": "user", "content": text}
        ]
        
        params['messages'] = messages
        params['schema'] = ClassificationResult
        
        return await self._structured_generate(params)
    
    async def _get_client(self, provider: str) -> Any:
        """Get or create client for provider"""
        if provider in self.clients:
            return self.clients[provider]
        
        client = await self._create_client(provider)
        self.clients[provider] = client
        return client
    
    async def _create_client(self, provider: str) -> Any:
        """Create client for provider"""
        import instructor
        
        if provider == "openai":
            try:
                from openai import OpenAI
                base_client = OpenAI()
                return instructor.from_openai(base_client)
            except ImportError:
                raise ProviderError("OpenAI library not installed. Run: pip install openai")
                
        elif provider == "anthropic":
            try:
                from anthropic import Anthropic
                base_client = Anthropic()
                return instructor.from_anthropic(base_client)
            except ImportError:
                raise ProviderError("Anthropic library not installed. Run: pip install anthropic")
                
        elif provider == "cohere":
            try:
                from cohere import Client as CohereClient
                base_client = CohereClient()
                return instructor.from_cohere(base_client)
            except ImportError:
                raise ProviderError("Cohere library not installed. Run: pip install cohere")
                
        elif provider == "litellm":
            try:
                import litellm
                return instructor.from_litellm(litellm.completion)
            except ImportError:
                raise ProviderError("LiteLLM library not installed. Run: pip install litellm")
                
        else:
            raise InvalidParameterError("provider", f"Unsupported provider: {provider}")
    
    def _convert_to_anthropic_format(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Convert OpenAI message format to Anthropic format"""
        anthropic_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            if role == 'system':
                # Anthropic doesn't have system role, prepend to first user message
                continue
            anthropic_messages.append({
                'role': 'user' if role == 'user' else 'assistant',
                'content': msg.get('content', '')
            })
        return anthropic_messages