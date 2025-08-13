"""
Ollama Provider for Gleitzeit V3

Ollama LLM provider that connects to the central server.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
import aiohttp

from .base import BaseProvider

logger = logging.getLogger(__name__)


class OllamaProvider(BaseProvider):
    """
    Ollama provider for V3 architecture
    
    Features:
    - Text generation
    - Vision analysis
    - Chat completions
    - Embeddings
    - Automatic model discovery
    """
    
    # Provider metadata for automatic discovery
    PROVIDER_TYPE = "ollama"
    SUPPORTED_FUNCTIONS = ["generate", "chat", "vision", "embed"]
    
    def __init__(
        self,
        provider_id: str = "ollama_provider",
        provider_name: str = "Ollama LLM Provider",
        ollama_url: str = "http://localhost:11434",
        server_url: str = "http://localhost:8000",
        max_concurrent_tasks: int = 4
    ):
        # Initialize with supported functions
        super().__init__(
            provider_id=provider_id,
            provider_name=provider_name,
            provider_type="llm",
            supported_functions=["generate", "chat", "vision", "embed"],
            server_url=server_url,
            max_concurrent_tasks=max_concurrent_tasks
        )
        
        self.ollama_url = ollama_url
        self.available_models = []
        
        logger.info(f"OllamaProvider initialized: {provider_name}")
    
    async def start(self):
        """Start the Ollama provider"""
        try:
            # Check Ollama availability
            await self._check_ollama_health()
            
            # Load available models
            await self._load_models()
            
            # Start base provider (connects to server)
            await super().start()
            
            logger.info(f"🚀 Ollama provider started with {len(self.available_models)} models")
            
        except Exception as e:
            logger.error(f"Failed to start Ollama provider: {e}")
            raise
    
    async def execute_task(self, task_type: str, parameters: Dict[str, Any]) -> Any:
        """Execute Ollama task based on function"""
        function = parameters.get("function", "generate")
        
        logger.info(f"Executing Ollama function: {function}")
        logger.debug(f"Parameters: {parameters}")
        
        if function == "generate":
            return await self._generate_text(parameters)
        elif function == "chat":
            return await self._chat(parameters)
        elif function == "vision":
            return await self._analyze_vision(parameters)
        elif function == "embed":
            return await self._embed_text(parameters)
        else:
            raise ValueError(f"Unsupported function: {function}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform Ollama health check"""
        try:
            # Check Ollama server
            healthy = await self._check_ollama_health()
            
            return {
                "healthy": healthy,
                "score": 1.0 if healthy else 0.0,
                "details": {
                    "ollama_url": self.ollama_url,
                    "models_available": len(self.available_models),
                    "models": self.available_models[:5] if self.available_models else []
                }
            }
        except Exception as e:
            return {
                "healthy": False,
                "score": 0.0,
                "details": {
                    "error": str(e)
                }
            }
    
    async def _generate_text(self, parameters: Dict[str, Any]) -> str:
        """Generate text using Ollama"""
        prompt = parameters.get('prompt', '')
        model = parameters.get('model', 'llama3')
        temperature = parameters.get('temperature', 0.7)
        max_tokens = parameters.get('max_tokens', 500)
        
        # Handle parameter substitution results
        if isinstance(prompt, dict) and 'content' in prompt:
            # This might be a result from another task
            if isinstance(prompt['content'], list):
                # Extract text from content array
                prompt = ' '.join([
                    item.get('text', '') 
                    for item in prompt['content'] 
                    if isinstance(item, dict) and 'text' in item
                ])
            else:
                prompt = str(prompt['content'])
        
        logger.info(f"Sending prompt to Ollama (length: {len(prompt)} chars)")
        logger.debug(f"Prompt preview: {prompt[:200]}...")
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_url}/api/generate", 
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('response', '')
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"Ollama API error {response.status}: {error_text}")
    
    async def _chat(self, parameters: Dict[str, Any]) -> str:
        """Chat using Ollama"""
        messages = parameters.get('messages', [])
        model = parameters.get('model', 'llama3')
        temperature = parameters.get('temperature', 0.7)
        
        # If no messages, use prompt
        if not messages and 'prompt' in parameters:
            messages = [{"role": "user", "content": parameters['prompt']}]
        
        payload = {
            'model': model,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': temperature
            }
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    message = result.get('message', {})
                    return message.get('content', '')
                else:
                    # Fallback to generate API
                    prompt = "\n".join([
                        f"{msg.get('role', 'user')}: {msg.get('content', '')}" 
                        for msg in messages
                    ])
                    return await self._generate_text({
                        'prompt': prompt,
                        'model': model,
                        'temperature': temperature
                    })
    
    async def _analyze_vision(self, parameters: Dict[str, Any]) -> str:
        """Analyze image using Ollama vision model"""
        prompt = parameters.get('prompt', 'Describe this image')
        model = parameters.get('model', 'llava')
        image_path = parameters.get('image_path')
        image_data = parameters.get('image_data')
        
        # Get image data
        if image_data:
            # Already have base64 data
            pass
        elif image_path:
            # Read from file
            import base64
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
        else:
            raise ValueError("Either image_path or image_data required for vision")
        
        payload = {
            'model': model,
            'prompt': prompt,
            'images': [image_data],
            'stream': False
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_url}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('response', '')
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"Ollama vision API error {response.status}: {error_text}")
    
    async def _embed_text(self, parameters: Dict[str, Any]) -> List[float]:
        """Generate embeddings using Ollama"""
        text = parameters.get('prompt', '')
        model = parameters.get('model', 'nomic-embed-text')
        
        payload = {
            'model': model,
            'prompt': text
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.ollama_url}/api/embeddings",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('embedding', [])
                else:
                    error_text = await response.text()
                    raise RuntimeError(f"Ollama embeddings API error {response.status}: {error_text}")
    
    async def _check_ollama_health(self) -> bool:
        """Check if Ollama is healthy"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.ollama_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Ollama health check failed: {response.status}")
                        return False
            
            logger.info("✅ Ollama server is healthy")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ollama server not available: {e}")
            return False
    
    async def _load_models(self):
        """Load available models from Ollama"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.ollama_url}/api/tags",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        self.available_models = [
                            model['name'] 
                            for model in data.get('models', [])
                        ]
                        logger.info(f"📋 Loaded {len(self.available_models)} models")
                        if self.available_models:
                            logger.info(f"   Available: {', '.join(self.available_models[:5])}")
                    else:
                        logger.warning(f"Failed to load models: {response.status}")
                        self.available_models = []
        
        except Exception as e:
            logger.warning(f"Error loading models: {e}")
            self.available_models = []


async def main():
    """Main function for running Ollama provider standalone"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ollama Provider for Gleitzeit V3")
    parser.add_argument('--ollama-url', default='http://localhost:11434', help='Ollama server URL')
    parser.add_argument('--server-url', default='http://localhost:8000', help='Central server URL')
    parser.add_argument('--provider-id', default='ollama_provider', help='Provider ID')
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and start provider
    provider = OllamaProvider(
        provider_id=args.provider_id,
        ollama_url=args.ollama_url,
        server_url=args.server_url
    )
    
    try:
        await provider.start()
        
        logger.info("🤖 Ollama provider running. Press Ctrl+C to stop.")
        
        # Keep running
        while True:
            await asyncio.sleep(60)
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    
    finally:
        await provider.stop()


if __name__ == '__main__':
    asyncio.run(main())