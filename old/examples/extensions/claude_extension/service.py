"""
Claude Extension Service - Config-based

This service implements the Claude extension functionality
as defined by the extension.yaml configuration.
"""

import asyncio
from typing import Dict, Any, Optional, List

from gleitzeit_extensions.config_loader import ConfigBasedExtension


class ClaudeService(ConfigBasedExtension):
    """Claude service for Gleitzeit cluster"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.client = None
        self._service_task = None
    
    async def setup(self) -> None:
        """Initialize Claude client"""
        try:
            import anthropic
            
            self.client = anthropic.AsyncAnthropic(
                api_key=self.config['api_key'],
                timeout=self.config.get('timeout', 60),
                max_retries=self.config.get('max_retries', 3),
                base_url=self.config.get('base_url', 'https://api.anthropic.com')
            )
            print(f"✅ Claude extension initialized")
            
        except ImportError:
            raise RuntimeError("Anthropic package not installed. Run: pip install anthropic")
    
    async def start(self) -> None:
        """Start Claude service"""
        print(f"🚀 Claude extension service started")
        # In a real implementation, this would start the Socket.IO event loop
        await asyncio.sleep(0)  # Placeholder for service startup
    
    async def stop(self) -> None:
        """Stop Claude service"""
        if self._service_task:
            self._service_task.cancel()
            try:
                await self._service_task
            except asyncio.CancelledError:
                pass
        print(f"🛑 Claude extension service stopped")
    
    def health_check(self) -> Dict[str, Any]:
        """Check Claude service health"""
        return {
            'healthy': self.client is not None,
            'provider': 'claude',
            'models': ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku'],
            'capabilities': ['text', 'streaming', 'function_calling']
        }
    
    def get_models(self) -> List[str]:
        """Get supported models"""
        return ['claude-3-opus', 'claude-3-sonnet', 'claude-3-haiku']
    
    def get_capabilities(self) -> List[str]:
        """Get supported capabilities"""
        return ['text', 'streaming', 'function_calling']
    
    async def handle_text_generation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text generation requests"""
        prompt = task_data.get('prompt', '')
        model = task_data.get('model', 'claude-3-haiku')
        
        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=task_data.get('max_tokens', 1000),
                temperature=task_data.get('temperature', 0.7),
                messages=[{"role": "user", "content": prompt}]
            )
            
            return {
                'success': True,
                'result': response.content[0].text,
                'model': model,
                'usage': {
                    'input_tokens': response.usage.input_tokens,
                    'output_tokens': response.usage.output_tokens
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'model': model
            }
    
    async def handle_streaming_generation(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle streaming text generation requests"""
        prompt = task_data.get('prompt', '')
        model = task_data.get('model', 'claude-3-haiku')
        
        try:
            stream = await self.client.messages.create(
                model=model,
                max_tokens=task_data.get('max_tokens', 1000),
                temperature=task_data.get('temperature', 0.7),
                messages=[{"role": "user", "content": prompt}],
                stream=True
            )
            
            # For this example, we collect the stream and return the full result
            # In a real implementation, this would stream via Socket.IO
            full_text = ""
            async for chunk in stream:
                if chunk.type == "content_block_delta":
                    full_text += chunk.delta.text
            
            return {
                'success': True,
                'result': full_text,
                'model': model,
                'streamed': True
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'model': model
            }