"""
Ollama Provider for Gleitzeit V4

Protocol-based Ollama LLM provider that implements the "llm/v1" protocol.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
import aiohttp
import json

from .base import ProtocolProvider

logger = logging.getLogger(__name__)


class OllamaProvider(ProtocolProvider):
    """
    Ollama provider for V4 protocol-based architecture
    
    Implements the "llm/v1" protocol with methods:
    - generate: Text generation
    - chat: Chat completions 
    - vision: Image analysis
    - embed: Text embeddings
    """
    
    def __init__(
        self,
        provider_id: str,
        ollama_url: str = "http://localhost:11434",
        timeout: int = 60
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id="llm/v1",
            name="Ollama LLM Provider",
            description="Ollama local LLM provider"
        )
        self.ollama_url = ollama_url
        self.timeout = timeout
        self.available_models = []
        self.session = None
        
        logger.info(f"Initialized OllamaProvider: {provider_id}")
    
    async def initialize(self):
        """Initialize the Ollama provider"""
        try:
            # Create HTTP session
            self.session = aiohttp.ClientSession()
            
            # Check Ollama health
            await self._check_ollama_health()
            
            # Load available models
            await self._load_models()
            
            logger.info(f"✅ Ollama provider initialized with {len(self.available_models)} models")
            
        except Exception as e:
            logger.error(f"Failed to initialize Ollama provider: {e}")
            raise
    
    async def shutdown(self):
        """Shutdown the Ollama provider"""
        if self.session:
            await self.session.close()
            self.session = None
        
        logger.info("Ollama provider shutdown")
    
    async def cleanup(self):
        """Cleanup method for compatibility with pooling system"""
        await self.shutdown()
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Ollama provider health"""
        try:
            healthy = await self._check_ollama_health()
            
            return {
                "status": "healthy" if healthy else "unhealthy",
                "details": {
                    "ollama_url": self.ollama_url,
                    "models_available": len(self.available_models),
                    "available_models": self.available_models[:5] if self.available_models else []
                }
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "details": {"error": str(e)}
            }
    
    def get_supported_methods(self) -> List[str]:
        """Get supported protocol methods"""
        return ["llm/chat", "llm/complete", "llm/vision"]
    
    async def handle_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Handle protocol request"""
        logger.info(f"Handling Ollama request: {method}")
        logger.debug(f"Parameters: {params}")
        
        if method == "llm/chat":
            return await self._chat(params)
        elif method == "llm/complete":
            return await self._generate_text(params)
        elif method == "llm/vision":
            return await self._handle_vision(params)
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    async def _generate_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate text using Ollama"""
        prompt = params.get('prompt', '')
        model = params.get('model', 'llama3')
        temperature = params.get('temperature', 0.7)
        max_tokens = params.get('max_tokens', 500)
        
        # Handle parameter substitution results
        if isinstance(prompt, dict) and 'content' in prompt:
            if isinstance(prompt['content'], list):
                # Extract text from content array
                prompt = ' '.join([
                    item.get('text', '') 
                    for item in prompt['content'] 
                    if isinstance(item, dict) and 'text' in item
                ])
            else:
                prompt = str(prompt['content'])
        
        logger.info(f"Generating text with model {model} (prompt length: {len(prompt)} chars)")
        
        payload = {
            'model': model,
            'prompt': prompt,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens
            }
        }
        
        async with self.session.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "content": result.get('response', ''),
                    "model": model,
                    "provider_id": self.provider_id,
                    "tokens_used": result.get('eval_count', 0),
                    "total_duration": result.get('total_duration', 0)
                }
            else:
                error_text = await response.text()
                raise RuntimeError(f"Ollama API error {response.status}: {error_text}")
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Chat using Ollama"""
        messages = params.get('messages', [])
        model = params.get('model', 'llama3')
        temperature = params.get('temperature', 0.7)
        max_tokens = params.get('max_tokens', 500)
        file_path = params.get('file_path')
        
        # If file_path is provided, read the file and add to messages
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                logger.info(f"Read file {file_path} ({len(file_content)} chars)")
                
                # Add file content to the last user message or create a new one
                if messages and messages[-1].get('role') == 'user':
                    # Append to last user message
                    original_content = messages[-1].get('content', '')
                    messages[-1]['content'] = f"{original_content}\n\nFile content from {file_path}:\n{file_content}"
                else:
                    # Create new user message with file content
                    messages.append({
                        "role": "user",
                        "content": f"File content from {file_path}:\n{file_content}"
                    })
            except Exception as e:
                logger.error(f"Error reading file {file_path}: {e}")
                return {
                    "content": f"Error reading file: {e}",
                    "role": "assistant",
                    "model": model,
                    "provider_id": self.provider_id,
                    "error": str(e)
                }
        
        # If no messages, use prompt
        if not messages and 'prompt' in params:
            messages = [{"role": "user", "content": params['prompt']}]
        
        logger.info(f"Chat with model {model} ({len(messages)} messages)")
        
        payload = {
            'model': model,
            'messages': messages,
            'stream': False,
            'options': {
                'temperature': temperature,
                'num_predict': max_tokens
            }
        }
        
        async with self.session.post(
            f"{self.ollama_url}/api/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as response:
            if response.status == 200:
                result = await response.json()
                message = result.get('message', {})
                return {
                    "content": message.get('content', ''),
                    "role": message.get('role', 'assistant'),
                    "model": model,
                    "provider_id": self.provider_id,
                    "tokens_used": result.get('eval_count', 0),
                    "total_duration": result.get('total_duration', 0)
                }
            else:
                # Fallback to generate API
                logger.warning(f"Chat API failed ({response.status}), falling back to generate")
                prompt = "\n".join([
                    f"{msg.get('role', 'user')}: {msg.get('content', '')}" 
                    for msg in messages
                ])
                return await self._generate_text({
                    'prompt': prompt,
                    'model': model,
                    'temperature': temperature,
                    'max_tokens': max_tokens
                })
    
    async def _handle_vision(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle vision method - routes to appropriate implementation"""
        messages = params.get('messages', [])
        images = params.get('images', [])
        image_path = params.get('image_path')
        
        # Extract images from messages if present
        for msg in messages:
            if 'images' in msg and msg['images']:
                images.extend(msg['images'])
        
        # If we have images or image_path, use vision analysis
        if images or image_path:
            # Get the prompt from the last user message
            prompt = 'Describe this image'
            for msg in reversed(messages):
                if msg.get('role') == 'user':
                    prompt = msg.get('content', prompt)
                    break
            
            return await self._analyze_vision({
                'prompt': prompt,
                'model': params.get('model', 'llava'),
                'image_data': images[0] if images else None,  # Use first image if available
                'image_path': image_path  # Pass through image_path
            })
        else:
            # No images, fallback to regular chat
            return await self._chat(params)
    
    async def _analyze_vision(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze image using Ollama vision model"""
        prompt = params.get('prompt', 'Describe this image')
        model = params.get('model', 'llava')
        image_path = params.get('image_path')
        image_data = params.get('image_data')
        
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
        
        logger.info(f"Vision analysis with model {model}")
        
        payload = {
            'model': model,
            'prompt': prompt,
            'images': [image_data],
            'stream': False
        }
        
        async with self.session.post(
            f"{self.ollama_url}/api/generate",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout * 2)  # Vision takes longer
        ) as response:
            if response.status == 200:
                result = await response.json()
                return {
                    "content": result.get('response', ''),
                    "model": model,
                    "provider_id": self.provider_id,
                    "tokens_used": result.get('eval_count', 0),
                    "total_duration": result.get('total_duration', 0)
                }
            else:
                error_text = await response.text()
                raise RuntimeError(f"Ollama vision API error {response.status}: {error_text}")
    
    async def _embed_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate embeddings using Ollama"""
        text = params.get('prompt', params.get('text', ''))
        model = params.get('model', 'nomic-embed-text')
        
        logger.info(f"Generating embeddings with model {model} (text length: {len(text)} chars)")
        
        payload = {
            'model': model,
            'prompt': text
        }
        
        async with self.session.post(
            f"{self.ollama_url}/api/embeddings",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status == 200:
                result = await response.json()
                embedding = result.get('embedding', [])
                return {
                    "embedding": embedding,
                    "model": model,
                    "provider_id": self.provider_id,
                    "dimensions": len(embedding)
                }
            else:
                error_text = await response.text()
                raise RuntimeError(f"Ollama embeddings API error {response.status}: {error_text}")
    
    async def _check_ollama_health(self) -> bool:
        """Check if Ollama is healthy"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()
            
            async with self.session.get(
                f"{self.ollama_url}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                healthy = response.status == 200
                if not healthy:
                    logger.warning(f"Ollama health check failed: {response.status}")
                else:
                    logger.debug("✅ Ollama server is healthy")
                return healthy
            
        except Exception as e:
            logger.error(f"❌ Ollama server not available: {e}")
            return False
    
    async def _load_models(self):
        """Load available models from Ollama"""
        try:
            async with self.session.get(
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
                    self.available_models = ['llama3']  # Fallback default
        
        except Exception as e:
            logger.warning(f"Error loading models: {e}")
            self.available_models = ['llama3']  # Fallback default