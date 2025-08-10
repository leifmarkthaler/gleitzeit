#!/usr/bin/env python3
"""
Local LLM Provider for Gleitzeit

Integrates with Ollama, llama.cpp, or other local LLM servers
"""

import asyncio
import json
import logging
from typing import Any, Dict, AsyncGenerator
import aiohttp
from gleitzeit_extensions.socketio_provider_client import SocketIOProviderClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OllamaProvider(SocketIOProviderClient):
    """Provider for Ollama local LLMs"""
    
    def __init__(self, ollama_url: str = "http://localhost:11434", **kwargs):
        # Store Ollama URL
        self.ollama_url = ollama_url
        
        # Get available models from Ollama (synchronously)
        import requests
        try:
            response = requests.get(f"{ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = [model["name"] for model in data.get("models", [])]
                logger.info(f"Found {len(models)} Ollama models: {models}")
            else:
                models = ["llama2", "mistral", "codellama"]
                logger.warning(f"Could not fetch Ollama models: HTTP {response.status_code}")
        except Exception as e:
            logger.warning(f"Could not fetch Ollama models: {e}")
            models = ["llama2", "mistral", "codellama"]
        
        # Remove 'name' from kwargs to avoid duplicate
        kwargs.pop('name', None)
        
        super().__init__(
            name="ollama",
            provider_type="llm",
            models=models,
            capabilities=["text", "code", "chat", "streaming"],
            description=f"Ollama local LLM server at {ollama_url}",
            **kwargs
        )
    
    async def _get_ollama_models(self, url: str) -> list:
        """Get list of available models from Ollama"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{url}/api/tags") as response:
                    if response.status == 200:
                        data = await response.json()
                        return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Could not fetch Ollama models: {e}")
        
        # Fallback to common models
        return ["llama2", "codellama", "mistral", "neural-chat"]
    
    async def invoke(self, method: str, **kwargs) -> Any:
        """Invoke LLM methods"""
        
        if method == "complete" or method == "generate":
            return await self._generate(kwargs)
        elif method == "chat":
            return await self._chat(kwargs)
        elif method == "embed":
            return await self._embed(kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate text completion"""
        prompt = params.get("prompt", "")
        model = params.get("model", self.models[0] if self.models else "llama2")
        max_tokens = params.get("max_tokens", 100)
        temperature = params.get("temperature", 0.7)
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature
            }
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            "response": result.get("response", ""),
                            "model": model,
                            "done": result.get("done", True),
                            "context": result.get("context", [])
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to generate with Ollama: {e}")
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Chat completion"""
        messages = params.get("messages", [])
        model = params.get("model", self.models[0] if self.models else "llama2")
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/chat",
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            "message": result.get("message", {}),
                            "model": model,
                            "done": result.get("done", True)
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama chat API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to chat with Ollama: {e}")
    
    async def _embed(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate embeddings"""
        text = params.get("text", "")
        model = params.get("model", "llama2")
        
        payload = {
            "model": model,
            "prompt": text
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/embeddings",
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            "embedding": result.get("embedding", []),
                            "model": model
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama embeddings API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to get embeddings from Ollama: {e}")
    
    async def stream(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream text generation"""
        prompt = kwargs.get("prompt", "")
        model = kwargs.get("model", self.models[0] if self.models else "llama2")
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ollama_url}/api/generate",
                    json=payload
                ) as response:
                    if response.status == 200:
                        async for line in response.content:
                            if line:
                                try:
                                    data = json.loads(line.decode())
                                    yield {
                                        "token": data.get("response", ""),
                                        "done": data.get("done", False),
                                        "model": model
                                    }
                                    if data.get("done"):
                                        break
                                except json.JSONDecodeError:
                                    continue
                    else:
                        error_text = await response.text()
                        raise Exception(f"Ollama streaming API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to stream from Ollama: {e}")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Check Ollama health"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.ollama_url}/api/tags", timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        return {
                            "healthy": True,
                            "ollama_url": self.ollama_url,
                            "models_count": len(data.get("models", [])),
                            "models": [m["name"] for m in data.get("models", [])]
                        }
                    else:
                        return {"healthy": False, "error": f"HTTP {response.status}"}
        except Exception as e:
            return {"healthy": False, "error": str(e)}


class LlamaCppProvider(SocketIOProviderClient):
    """Provider for llama.cpp server"""
    
    def __init__(self, server_url: str = "http://localhost:8080", model_name: str = "local-model", **kwargs):
        super().__init__(
            name="llama-cpp",
            provider_type="llm", 
            models=[model_name],
            capabilities=["text", "code", "streaming"],
            description=f"llama.cpp server at {server_url}",
            **kwargs
        )
        self.server_url = server_url
        self.model_name = model_name
    
    async def invoke(self, method: str, **kwargs) -> Any:
        """Invoke llama.cpp methods"""
        
        if method == "complete" or method == "generate":
            return await self._generate(kwargs)
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def _generate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate completion using llama.cpp"""
        prompt = params.get("prompt", "")
        max_tokens = params.get("max_tokens", 100)
        temperature = params.get("temperature", 0.7)
        
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": temperature,
            "stream": False
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.server_url}/completion",
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return {
                            "response": result.get("content", ""),
                            "model": self.model_name,
                            "tokens": result.get("tokens_predicted", 0)
                        }
                    else:
                        error_text = await response.text()
                        raise Exception(f"llama.cpp API error {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"Failed to generate with llama.cpp: {e}")
    
    async def get_health_status(self) -> Dict[str, Any]:
        """Check llama.cpp server health"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.server_url}/health", timeout=5) as response:
                    return {
                        "healthy": response.status == 200,
                        "server_url": self.server_url,
                        "model": self.model_name
                    }
        except Exception as e:
            return {"healthy": False, "error": str(e)}


async def main():
    """Run local LLM providers"""
    print("🚀 Starting Local LLM Providers")
    print("=" * 50)
    
    providers = []
    
    # Start Ollama provider (if available)
    print("1. Starting Ollama provider...")
    try:
        ollama = OllamaProvider()  # Connect to Gleitzeit server, not Ollama directly
        providers.append(asyncio.create_task(ollama.run()))
        print("   ✅ Ollama provider started")
    except Exception as e:
        print(f"   ❌ Ollama provider failed: {e}")
    
    # Start llama.cpp provider (if available)  
    print("2. Starting llama.cpp provider...")
    try:
        llamacpp = LlamaCppProvider(
            model_name="my-local-model"
        )  # Connect to Gleitzeit server
        providers.append(asyncio.create_task(llamacpp.run()))
        print("   ✅ llama.cpp provider started")
    except Exception as e:
        print(f"   ❌ llama.cpp provider failed: {e}")
    
    if not providers:
        print("❌ No providers started. Make sure Ollama or llama.cpp server is running.")
        return
    
    print(f"\n🎉 {len(providers)} provider(s) running!")
    print("\nUse these commands:")
    print("  gleitzeit providers list")
    print("  gleitzeit providers models") 
    print("  gleitzeit providers invoke ollama generate --args '{\"prompt\": \"Hello!\", \"model\": \"llama2\"}'")
    print("\nPress Ctrl+C to stop...")
    
    try:
        await asyncio.gather(*providers)
    except KeyboardInterrupt:
        print("\n🛑 Stopping providers...")
        for task in providers:
            task.cancel()
        print("👋 Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())