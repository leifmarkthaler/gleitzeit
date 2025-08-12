"""
Ollama Provider for Gleitzeit V2

Clean provider implementation using Socket.IO communication.
"""

import asyncio
import logging
from typing import Dict, Any, List
import aiohttp
import socketio

from ..core.models import TaskType

logger = logging.getLogger(__name__)


class OllamaProvider:
    """
    Ollama provider using Socket.IO communication
    
    Features:
    - Clean Socket.IO integration
    - Support for text generation and vision
    - Model management
    - Health monitoring
    """
    
    def __init__(
        self,
        provider_id: str = "ollama_provider",
        provider_name: str = "Ollama LLM Provider",
        ollama_url: str = "http://localhost:11434",
        server_url: str = "http://localhost:8000"
    ):
        self.provider_id = provider_id
        self.provider_name = provider_name
        self.ollama_url = ollama_url
        self.server_url = server_url
        
        # Socket.IO client
        self.sio = socketio.AsyncClient()
        
        # Provider state
        self.connected = False
        self.registered = False
        self.available_models = []
        self.current_tasks = 0
        self.max_concurrent = 4
        
        # Setup handlers
        self._setup_handlers()
        
        logger.info(f"OllamaProvider initialized: {provider_name}")
    
    def _setup_handlers(self):
        """Setup Socket.IO event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info("✅ Connected to central Socket.IO server")
            
            # Register as provider
            await self._register_provider()
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            self.registered = False
            logger.info("🔌 Disconnected from central Socket.IO server")
        
        @self.sio.on('provider:registered')
        async def provider_registered(data):
            self.registered = True
            logger.info(f"✅ Provider registered: {data.get('provider_id')}")
        
        @self.sio.on('task:assign')
        async def task_assign(data):
            """Handle task assignment"""
            task_id = data.get('task_id')
            logger.info(f"📋 Received task: {task_id}")
            
            # Process task in background
            asyncio.create_task(self._process_task(data))
        
        @self.sio.event
        async def error(data):
            message = data.get('message', 'Unknown error')
            logger.error(f"Server error: {message}")
    
    async def start(self):
        """Start the provider"""
        try:
            # Check Ollama availability
            await self._check_ollama_health()
            
            # Load available models
            await self._load_models()
            
            # Connect to server
            await self.sio.connect(self.server_url)
            
            logger.info("🚀 Ollama provider started")
            
        except Exception as e:
            logger.error(f"Failed to start Ollama provider: {e}")
            raise
    
    async def stop(self):
        """Stop the provider"""
        if self.connected:
            await self.sio.disconnect()
        
        logger.info("🛑 Ollama provider stopped")
    
    async def _register_provider(self):
        """Register with the server"""
        capabilities = {
            'task_types': [
                TaskType.LLM_GENERATE.value,
                TaskType.LLM_CHAT.value,
                TaskType.LLM_VISION.value,
                TaskType.LLM_EMBED.value
            ],
            'models': self.available_models,
            'max_concurrent': self.max_concurrent,
            'features': ['streaming', 'vision', 'embeddings']
        }
        
        await self.sio.emit('provider:register', {
            'provider': {
                'id': self.provider_id,
                'name': self.provider_name,
                'type': 'llm',
                'capabilities': capabilities
            }
        })
    
    async def _process_task(self, task_data: Dict[str, Any]):
        """Process assigned task"""
        task_id = task_data.get('task_id')
        workflow_id = task_data.get('workflow_id')
        task_type = task_data.get('task_type')
        parameters = task_data.get('parameters', {})
        
        try:
            self.current_tasks += 1
            
            # Acknowledge task
            await self.sio.emit('task:accepted', {
                'task_id': task_id,
                'provider_id': self.provider_id,
                'workflow_id': workflow_id
            })
            
            logger.info(f"🔄 Processing task: {task_id} (type: {task_type})")
            
            # Route to appropriate handler
            if task_type == TaskType.LLM_GENERATE.value:
                result = await self._generate_text(parameters)
            elif task_type == TaskType.LLM_VISION.value:
                result = await self._analyze_vision(parameters)
            elif task_type == TaskType.LLM_CHAT.value:
                result = await self._chat(parameters)
            elif task_type == TaskType.LLM_EMBED.value:
                result = await self._embed_text(parameters)
            else:
                raise ValueError(f"Unsupported task type: {task_type}")
            
            # Report success
            await self.sio.emit('task:completed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'provider_id': self.provider_id,
                'result': result
            })
            
            logger.info(f"✅ Task completed: {task_id}")
            
        except Exception as e:
            logger.error(f"❌ Task failed: {task_id} - {e}")
            
            # Report failure
            await self.sio.emit('task:failed', {
                'task_id': task_id,
                'workflow_id': workflow_id,
                'provider_id': self.provider_id,
                'error': str(e)
            })
            
        finally:
            self.current_tasks = max(0, self.current_tasks - 1)
    
    async def _generate_text(self, parameters: Dict[str, Any]) -> str:
        """Generate text using Ollama"""
        prompt = parameters.get('prompt', '')
        model = parameters.get('model', 'llama3')
        temperature = parameters.get('temperature', 0.7)
        max_tokens = parameters.get('max_tokens', 500)
        
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
            async with session.post(f"{self.ollama_url}/api/generate", json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('response', '')
                else:
                    raise RuntimeError(f"Ollama API error: {response.status}")
    
    async def _analyze_vision(self, parameters: Dict[str, Any]) -> str:
        """Analyze image using Ollama vision model"""
        prompt = parameters.get('prompt', 'Describe this image')
        model = parameters.get('model', 'llava')
        image_path = parameters.get('image_path', '')
        
        # Read image file
        import base64
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        payload = {
            'model': model,
            'prompt': prompt,
            'images': [image_data],
            'stream': False
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.ollama_url}/api/generate", json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('response', '')
                else:
                    raise RuntimeError(f"Ollama vision API error: {response.status}")
    
    async def _chat(self, parameters: Dict[str, Any]) -> str:
        """Chat using Ollama"""
        # Simplified chat implementation
        messages = parameters.get('messages', [])
        model = parameters.get('model', 'llama3')
        
        # Convert to simple prompt for now
        prompt = "\n".join([f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in messages])
        
        return await self._generate_text({
            'prompt': prompt,
            'model': model,
            'temperature': parameters.get('temperature', 0.7)
        })
    
    async def _embed_text(self, parameters: Dict[str, Any]) -> List[float]:
        """Generate embeddings using Ollama"""
        text = parameters.get('prompt', '')
        model = parameters.get('model', 'nomic-embed-text')
        
        payload = {
            'model': model,
            'prompt': text
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.ollama_url}/api/embeddings", json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    return result.get('embedding', [])
                else:
                    raise RuntimeError(f"Ollama embeddings API error: {response.status}")
    
    async def _check_ollama_health(self):
        """Check if Ollama is healthy"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags", timeout=5) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Ollama health check failed: {response.status}")
            
            logger.info("✅ Ollama server is healthy")
            
        except Exception as e:
            logger.error(f"❌ Ollama server not available: {e}")
            raise
    
    async def _load_models(self):
        """Load available models from Ollama"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        self.available_models = [model['name'] for model in data.get('models', [])]
                        logger.info(f"📋 Loaded {len(self.available_models)} models: {self.available_models}")
                    else:
                        logger.warning(f"Failed to load models: {response.status}")
                        self.available_models = ['llama3']  # Fallback
        
        except Exception as e:
            logger.warning(f"Error loading models: {e}")
            self.available_models = ['llama3']  # Fallback


async def main():
    """Main function for running provider standalone"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Ollama Provider for Gleitzeit V2")
    parser.add_argument('--ollama-url', default='http://localhost:11434', help='Ollama server URL')
    parser.add_argument('--server-url', default='http://localhost:8000', help='Gleitzeit server URL')
    parser.add_argument('--provider-id', default='ollama_provider', help='Provider ID')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Create and start provider
    provider = OllamaProvider(
        provider_id=args.provider_id,
        ollama_url=args.ollama_url,
        server_url=args.server_url
    )
    
    try:
        await provider.start()
        
        # Keep running
        while True:
            await asyncio.sleep(10)
            
            # Send heartbeat
            if provider.registered:
                await provider.sio.emit('provider:heartbeat', {
                    'provider_id': provider.provider_id
                })
    
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down...")
    
    finally:
        await provider.stop()


if __name__ == '__main__':
    asyncio.run(main())