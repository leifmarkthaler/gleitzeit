"""
Ollama client for LLM and vision model integration
"""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import httpx
from PIL import Image
import io

from ..core.task import Task, TaskType


class OllamaError(Exception):
    """Base exception for Ollama-related errors"""
    pass


class ModelNotFoundError(OllamaError):
    """Raised when a requested model is not available"""
    pass


class OllamaClient:
    """
    Async client for Ollama API integration
    
    Handles both text and vision model requests with proper error handling,
    streaming support, and automatic retries.
    """
    
    def __init__(
        self, 
        base_url: str = "http://localhost:11434",
        timeout: int = 300,
        max_retries: int = 3
    ):
        """
        Initialize Ollama client
        
        Args:
            base_url: Ollama server URL
            timeout: Request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5)
        )
        self._available_models: Optional[List[str]] = None
        self._model_info_cache: Dict[str, Dict[str, Any]] = {}
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
    
    async def close(self):
        """Close the HTTP client"""
        if self._client:
            await self._client.aclose()
    
    async def health_check(self) -> bool:
        """Check if Ollama server is healthy"""
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False
    
    async def list_models(self, force_refresh: bool = False) -> List[str]:
        """
        List available models
        
        Args:
            force_refresh: Force refresh of model list cache
            
        Returns:
            List of available model names
        """
        if self._available_models is None or force_refresh:
            try:
                response = await self._client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                
                data = response.json()
                self._available_models = [
                    model["name"].split(":")[0]  # Remove tag (e.g., ":latest")
                    for model in data.get("models", [])
                ]
            except Exception as e:
                raise OllamaError(f"Failed to fetch model list: {e}")
        
        return self._available_models or []
    
    async def pull_model(self, model_name: str) -> bool:
        """
        Pull a model if not available
        
        Args:
            model_name: Name of model to pull
            
        Returns:
            True if model was pulled or already available
        """
        available_models = await self.list_models()
        if model_name in available_models:
            return True
        
        try:
            print(f"🔽 Pulling model: {model_name}")
            
            async with self._client.stream(
                "POST",
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                timeout=3600  # Model pulls can take a long time
            ) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            data = json.loads(line)
                            if "status" in data:
                                print(f"   {data['status']}")
                            if data.get("error"):
                                raise OllamaError(f"Model pull failed: {data['error']}")
                        except json.JSONDecodeError:
                            continue
            
            # Refresh model list
            await self.list_models(force_refresh=True)
            print(f"✅ Model pulled successfully: {model_name}")
            return True
            
        except Exception as e:
            print(f"❌ Failed to pull model {model_name}: {e}")
            return False
    
    async def generate_text(
        self,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        stream: bool = False
    ) -> str:
        """
        Generate text using a language model
        
        Args:
            model: Model name to use
            prompt: Input prompt
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            stream: Whether to stream response
            
        Returns:
            Generated text response
        """
        # Ensure model is available
        available_models = await self.list_models()
        if model not in available_models:
            if not await self.pull_model(model):
                raise ModelNotFoundError(f"Model '{model}' not available and could not be pulled")
        
        # Prepare request
        request_data = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            request_data["options"]["num_predict"] = max_tokens
            
        if system_prompt:
            request_data["system"] = system_prompt
        
        # Make request with retries
        for attempt in range(self.max_retries):
            try:
                if stream:
                    return await self._generate_streaming(request_data)
                else:
                    return await self._generate_non_streaming(request_data)
                    
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise OllamaError(f"Text generation failed after {self.max_retries} attempts: {e}")
                
                # Wait before retry
                await asyncio.sleep(2 ** attempt)
        
        raise OllamaError("Unexpected error in text generation")
    
    async def generate_vision(
        self,
        model: str,
        prompt: str,
        image_path: Union[str, Path],
        temperature: float = 0.4,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Generate text response to image using vision model
        
        Args:
            model: Vision model name (e.g., "llava")
            prompt: Text prompt about the image
            image_path: Path to image file
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response about the image
        """
        # Ensure model is available
        available_models = await self.list_models()
        if model not in available_models:
            if not await self.pull_model(model):
                raise ModelNotFoundError(f"Vision model '{model}' not available and could not be pulled")
        
        # Encode image
        image_base64 = await self._encode_image(image_path)
        
        # Prepare request
        request_data = {
            "model": model,
            "prompt": prompt,
            "images": [image_base64],
            "stream": False,
            "options": {
                "temperature": temperature,
            }
        }
        
        if max_tokens:
            request_data["options"]["num_predict"] = max_tokens
        
        # Make request with retries
        for attempt in range(self.max_retries):
            try:
                response = await self._client.post(
                    f"{self.base_url}/api/generate",
                    json=request_data
                )
                response.raise_for_status()
                
                data = response.json()
                if "error" in data:
                    raise OllamaError(f"Vision generation error: {data['error']}")
                
                return data.get("response", "").strip()
                
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise OllamaError(f"Vision generation failed after {self.max_retries} attempts: {e}")
                
                await asyncio.sleep(2 ** attempt)
        
        raise OllamaError("Unexpected error in vision generation")
    
    async def _generate_non_streaming(self, request_data: Dict[str, Any]) -> str:
        """Generate text without streaming"""
        response = await self._client.post(
            f"{self.base_url}/api/generate",
            json=request_data
        )
        response.raise_for_status()
        
        data = response.json()
        if "error" in data:
            raise OllamaError(f"Generation error: {data['error']}")
        
        return data.get("response", "").strip()
    
    async def _generate_streaming(self, request_data: Dict[str, Any]) -> str:
        """Generate text with streaming response"""
        full_response = ""
        
        async with self._client.stream(
            "POST",
            f"{self.base_url}/api/generate",
            json=request_data
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        data = json.loads(line)
                        if "error" in data:
                            raise OllamaError(f"Streaming error: {data['error']}")
                        
                        if "response" in data:
                            full_response += data["response"]
                        
                        if data.get("done", False):
                            break
                            
                    except json.JSONDecodeError:
                        continue
        
        return full_response.strip()
    
    async def _encode_image(self, image_path: Union[str, Path]) -> str:
        """
        Encode image file to base64 string
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64 encoded image string
        """
        image_path = Path(image_path)
        
        if not image_path.exists():
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        try:
            # Read and potentially resize image
            with Image.open(image_path) as img:
                # Convert to RGB if necessary
                if img.mode != "RGB":
                    img = img.convert("RGB")
                
                # Resize if too large (Ollama has size limits)
                max_size = 1024
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                
                # Convert to base64
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=85)
                image_bytes = buffer.getvalue()
                
                return base64.b64encode(image_bytes).decode("utf-8")
                
        except Exception as e:
            raise OllamaError(f"Failed to encode image {image_path}: {e}")
    
    async def get_model_info(self, model_name: str) -> Dict[str, Any]:
        """
        Get detailed information about a model
        
        Args:
            model_name: Name of model to inspect
            
        Returns:
            Model information dictionary
        """
        if model_name in self._model_info_cache:
            return self._model_info_cache[model_name]
        
        try:
            response = await self._client.post(
                f"{self.base_url}/api/show",
                json={"name": model_name}
            )
            response.raise_for_status()
            
            model_info = response.json()
            self._model_info_cache[model_name] = model_info
            return model_info
            
        except Exception as e:
            raise OllamaError(f"Failed to get model info for {model_name}: {e}")
    
    def get_recommended_models(self) -> Dict[str, List[str]]:
        """Get recommended models for different task types"""
        return {
            "text": ["llama3.1", "llama3", "mistral", "codellama"],
            "vision": ["llava", "llava:13b", "bakllava"],
            "code": ["codellama", "deepseek-coder", "starcoder"],
            "chat": ["llama3.1", "mistral", "vicuna"]
        }
    
    def __str__(self) -> str:
        return f"OllamaClient(base_url={self.base_url})"