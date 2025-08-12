"""
OpenAI Extension Example - Decorator-based

This example shows how to create an extension for OpenAI using decorators.
"""

import asyncio
from typing import Dict, Any, Optional, List

from gleitzeit_extensions.decorators import (
    extension, requires, model, capability, config_field, handler
)


@requires("openai>=1.0.0", "tiktoken>=0.5.0")
@model("gpt-4", capabilities=["text", "vision"], max_tokens=8192, cost_per_token=0.00003)
@model("gpt-4-turbo", capabilities=["text", "vision"], max_tokens=128000, cost_per_token=0.00001)
@model("gpt-3.5-turbo", capabilities=["text"], max_tokens=4096, cost_per_token=0.0000015)
@capability("streaming", "function_calling")
@config_field("api_key", required=True, env_var="OPENAI_API_KEY", description="OpenAI API key")
@config_field("organization", env_var="OPENAI_ORG", description="OpenAI organization ID")
@config_field("timeout", field_type="integer", default=60, description="Request timeout in seconds")
@config_field("max_retries", field_type="integer", default=3, description="Maximum retry attempts")
@extension(
    name="openai",
    description="OpenAI GPT models integration",
    version="1.0.0",
    author="Gleitzeit Team"
)
class OpenAIExtension:
    """OpenAI extension for Gleitzeit cluster"""
    
    def __init__(self, api_key: str, organization: Optional[str] = None, 
                 timeout: int = 60, max_retries: int = 3, **kwargs):
        self.api_key = api_key
        self.organization = organization
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = None
        self._service_task = None
    
    async def setup(self) -> None:
        """Initialize OpenAI client"""
        try:
            import openai
            self.client = openai.AsyncOpenAI(
                api_key=self.api_key,
                organization=self.organization,
                timeout=self.timeout,
                max_retries=self.max_retries
            )
            print(f"✅ OpenAI extension initialized")
        except ImportError:
            raise RuntimeError("OpenAI package not installed. Run: pip install openai")
    
    async def start(self) -> None:
        """Start OpenAI service (Socket.IO handler)"""
        print(f"🚀 OpenAI extension service started")
        # In a real implementation, this would start the Socket.IO event loop
        await asyncio.sleep(0)  # Placeholder for service startup
    
    async def stop(self) -> None:
        """Stop OpenAI service"""
        if self._service_task:
            self._service_task.cancel()
            try:
                await self._service_task
            except asyncio.CancelledError:
                pass
        print(f"🛑 OpenAI extension service stopped")
    
    def health_check(self) -> Dict[str, Any]:
        """Check OpenAI service health"""
        return {
            'healthy': self.client is not None,
            'provider': 'openai',
            'models': ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo'],
            'capabilities': ['text', 'vision', 'streaming', 'function_calling']
        }
    
    def get_models(self) -> List[str]:
        """Get supported models"""
        return ['gpt-4', 'gpt-4-turbo', 'gpt-3.5-turbo']
    
    def get_capabilities(self) -> List[str]:
        """Get supported capabilities"""
        return ['text', 'vision', 'streaming', 'function_calling']
    
    async def generate_text(self, prompt: str, model: str = "gpt-3.5-turbo", **kwargs) -> str:
        """Generate text using OpenAI models"""
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=kwargs.get('temperature', 0.7),
                max_tokens=kwargs.get('max_tokens', 1000)
            )
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"OpenAI generation failed: {e}")
    
    async def generate_vision(self, prompt: str, image_url: str, model: str = "gpt-4", **kwargs) -> str:
        """Generate text from image + text using OpenAI vision models"""
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }],
                temperature=kwargs.get('temperature', 0.7),
                max_tokens=kwargs.get('max_tokens', 1000)
            )
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(f"OpenAI vision generation failed: {e}")
    
    @handler("text_generation")
    async def handle_text_generation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text generation requests via Socket.IO"""
        prompt = task_data.get('prompt', '')
        model = task_data.get('model', 'gpt-3.5-turbo')
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=task_data.get('temperature', 0.7),
                max_tokens=task_data.get('max_tokens', 1000)
            )
            
            return {
                'success': True,
                'result': response.choices[0].message.content,
                'model': model,
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'model': model
            }
    
    @handler("vision_generation")
    async def handle_vision_generation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle vision + text generation requests"""
        prompt = task_data.get('prompt', '')
        image_url = task_data.get('image_url', '')
        model = task_data.get('model', 'gpt-4')
        
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }],
                temperature=task_data.get('temperature', 0.7),
                max_tokens=task_data.get('max_tokens', 1000)
            )
            
            return {
                'success': True,
                'result': response.choices[0].message.content,
                'model': model,
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'model': model
            }


# This extension will be auto-discovered by the extension manager
# when placed in an extensions search path