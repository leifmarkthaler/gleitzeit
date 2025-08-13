#!/usr/bin/env python3
"""
External LLM Provider Services

Socket.IO services for external LLM providers (OpenAI, Anthropic, etc.)
Allows seamless integration of external LLM APIs into Gleitzeit workflows.
"""

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, Any, Optional
import aiohttp

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.external_service_node import (
    ExternalServiceNode,
    ExternalServiceCapability
)


class OpenAIService(ExternalServiceNode):
    """External service for OpenAI API integration"""
    
    def __init__(
        self,
        api_key: str,
        service_name: str = "OpenAI Service",
        cluster_url: str = "http://localhost:8000",
        max_concurrent_tasks: int = 10,
        default_model: str = "gpt-3.5-turbo"
    ):
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[ExternalServiceCapability.LLM_GENERATION],
            max_concurrent_tasks=max_concurrent_tasks
        )
        
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = "https://api.openai.com/v1"
        
        # Register handlers
        self.register_task_handler("llm_generation", self.execute_llm_task)
        self.register_task_handler("openai", self.execute_llm_task)
        
        # Track metrics
        self.metrics = {
            'total_requests': 0,
            'total_failures': 0,
            'total_tokens': 0,
            'avg_response_time': 0
        }
    
    async def execute_llm_task(self, task_data: dict) -> dict:
        """Execute OpenAI API request"""
        start_time = time.time()
        
        try:
            params = task_data.get('parameters', {})
            
            # Extract parameters
            if 'external_parameters' in params:
                exec_params = params['external_parameters']
            else:
                exec_params = params
            
            prompt = exec_params.get('prompt')
            model = exec_params.get('model', self.default_model)
            temperature = exec_params.get('temperature', 0.7)
            max_tokens = exec_params.get('max_tokens', 1000)
            
            if not prompt:
                raise ValueError("No prompt provided")
            
            print(f"🤖 OpenAI API call: {model}")
            
            # Make API request
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"OpenAI API error {response.status}: {error_text}")
                    
                    result = await response.json()
            
            # Extract response
            content = result['choices'][0]['message']['content']
            usage = result.get('usage', {})
            
            # Update metrics
            execution_time = time.time() - start_time
            self.metrics['total_requests'] += 1
            self.metrics['total_tokens'] += usage.get('total_tokens', 0)
            self._update_avg_response_time(execution_time)
            
            print(f"✅ OpenAI completed in {execution_time:.2f}s")
            
            return {
                'success': True,
                'result': content,
                'model': model,
                'execution_time': execution_time,
                'tokens_used': usage.get('total_tokens', 0),
                'provider': 'openai'
            }
            
        except Exception as e:
            self.metrics['total_failures'] += 1
            error_msg = f"OpenAI API failed: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                'success': False,
                'error': error_msg,
                'execution_time': time.time() - start_time,
                'provider': 'openai'
            }
    
    def _update_avg_response_time(self, new_time: float):
        """Update average response time"""
        total = self.metrics['total_requests']
        if total == 1:
            self.metrics['avg_response_time'] = new_time
        else:
            avg = self.metrics['avg_response_time']
            self.metrics['avg_response_time'] = ((avg * (total - 1) + new_time) / total)


class AnthropicService(ExternalServiceNode):
    """External service for Anthropic/Claude API integration"""
    
    def __init__(
        self,
        api_key: str,
        service_name: str = "Anthropic Service",
        cluster_url: str = "http://localhost:8000",
        max_concurrent_tasks: int = 10,
        default_model: str = "claude-3-sonnet-20240229"
    ):
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[ExternalServiceCapability.LLM_GENERATION],
            max_concurrent_tasks=max_concurrent_tasks
        )
        
        self.api_key = api_key
        self.default_model = default_model
        self.base_url = "https://api.anthropic.com/v1"
        
        # Register handlers
        self.register_task_handler("llm_generation", self.execute_llm_task)
        self.register_task_handler("claude", self.execute_llm_task)
        self.register_task_handler("anthropic", self.execute_llm_task)
        
        # Track metrics
        self.metrics = {
            'total_requests': 0,
            'total_failures': 0,
            'total_tokens': 0,
            'avg_response_time': 0
        }
    
    async def execute_llm_task(self, task_data: dict) -> dict:
        """Execute Anthropic API request"""
        start_time = time.time()
        
        try:
            params = task_data.get('parameters', {})
            
            # Extract parameters
            if 'external_parameters' in params:
                exec_params = params['external_parameters']
            else:
                exec_params = params
            
            prompt = exec_params.get('prompt')
            model = exec_params.get('model', self.default_model)
            temperature = exec_params.get('temperature', 0.7)
            max_tokens = exec_params.get('max_tokens', 1000)
            
            if not prompt:
                raise ValueError("No prompt provided")
            
            print(f"🤖 Anthropic API call: {model}")
            
            # Make API request
            headers = {
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }
            
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}]
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300)
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Anthropic API error {response.status}: {error_text}")
                    
                    result = await response.json()
            
            # Extract response
            content = result['content'][0]['text']
            usage = result.get('usage', {})
            
            # Update metrics
            execution_time = time.time() - start_time
            self.metrics['total_requests'] += 1
            self.metrics['total_tokens'] += usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
            self._update_avg_response_time(execution_time)
            
            print(f"✅ Anthropic completed in {execution_time:.2f}s")
            
            return {
                'success': True,
                'result': content,
                'model': model,
                'execution_time': execution_time,
                'tokens_used': usage.get('input_tokens', 0) + usage.get('output_tokens', 0),
                'provider': 'anthropic'
            }
            
        except Exception as e:
            self.metrics['total_failures'] += 1
            error_msg = f"Anthropic API failed: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                'success': False,
                'error': error_msg,
                'execution_time': time.time() - start_time,
                'provider': 'anthropic'
            }
    
    def _update_avg_response_time(self, new_time: float):
        """Update average response time"""
        total = self.metrics['total_requests']
        if total == 1:
            self.metrics['avg_response_time'] = new_time
        else:
            avg = self.metrics['avg_response_time']
            self.metrics['avg_response_time'] = ((avg * (total - 1) + new_time) / total)


class MockLLMService(ExternalServiceNode):
    """Mock LLM service for testing without real API calls"""
    
    def __init__(
        self,
        service_name: str = "Mock LLM Service",
        cluster_url: str = "http://localhost:8000",
        response_delay: float = 1.0
    ):
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[ExternalServiceCapability.LLM_GENERATION],
            max_concurrent_tasks=5
        )
        
        self.response_delay = response_delay
        
        # Register handlers
        self.register_task_handler("llm_generation", self.execute_llm_task)
        self.register_task_handler("mock", self.execute_llm_task)
    
    async def execute_llm_task(self, task_data: dict) -> dict:
        """Execute mock LLM task"""
        start_time = time.time()
        
        try:
            params = task_data.get('parameters', {})
            
            if 'external_parameters' in params:
                exec_params = params['external_parameters']
            else:
                exec_params = params
            
            prompt = exec_params.get('prompt', '')
            model = exec_params.get('model', 'mock-model')
            
            print(f"🎭 Mock LLM: {model}")
            print(f"   Prompt: {prompt[:50]}{'...' if len(prompt) > 50 else ''}")
            
            # Simulate processing time
            await asyncio.sleep(self.response_delay)
            
            # Generate mock response based on prompt
            if "analyze" in prompt.lower():
                response = f"Analysis of the provided content shows key patterns and insights. Based on the input, I recommend the following strategic approach..."
            elif "summarize" in prompt.lower():
                response = f"Summary: The main points are clearly outlined with actionable recommendations for next steps."
            elif "translate" in prompt.lower():
                response = f"Translation: [Translated content would appear here in target language]"
            else:
                response = f"Response to '{prompt[:30]}...': This is a mock LLM response demonstrating the unified Socket.IO architecture."
            
            execution_time = time.time() - start_time
            
            print(f"✅ Mock LLM completed in {execution_time:.2f}s")
            
            return {
                'success': True,
                'result': response,
                'model': model,
                'execution_time': execution_time,
                'provider': 'mock'
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'execution_time': time.time() - start_time,
                'provider': 'mock'
            }


# ============================================
# Multi-Provider Service Manager
# ============================================

class MultiProviderLLMManager:
    """Manages multiple LLM provider services"""
    
    def __init__(self):
        self.services = {}
        self.running_services = []
    
    def add_openai_service(self, api_key: str, service_name: str = "OpenAI"):
        """Add OpenAI service"""
        self.services[service_name] = OpenAIService(
            api_key=api_key,
            service_name=service_name
        )
    
    def add_anthropic_service(self, api_key: str, service_name: str = "Anthropic"):
        """Add Anthropic service"""
        self.services[service_name] = AnthropicService(
            api_key=api_key,
            service_name=service_name
        )
    
    def add_mock_service(self, service_name: str = "Mock LLM", delay: float = 1.0):
        """Add mock service for testing"""
        self.services[service_name] = MockLLMService(
            service_name=service_name,
            response_delay=delay
        )
    
    async def start_all(self):
        """Start all configured services"""
        print(f"🚀 Starting {len(self.services)} LLM provider services...")
        
        for name, service in self.services.items():
            try:
                print(f"   Starting {name}...")
                task = asyncio.create_task(service.start())
                self.running_services.append((name, service, task))
                await asyncio.sleep(0.5)  # Stagger startup
            except Exception as e:
                print(f"   ❌ Failed to start {name}: {e}")
        
        print(f"✅ Started {len(self.running_services)} services")
    
    async def stop_all(self):
        """Stop all services"""
        print("🛑 Stopping all LLM provider services...")
        
        for name, service, task in self.running_services:
            try:
                await service.stop()
                task.cancel()
                print(f"   ✅ Stopped {name}")
            except Exception as e:
                print(f"   ⚠️ Error stopping {name}: {e}")
        
        self.running_services.clear()


# ============================================
# Usage Examples
# ============================================

async def demo_multi_provider():
    """Demonstrate multiple LLM providers working together"""
    
    print("🌐 Multi-Provider LLM Demo")
    print("=" * 40)
    
    # Setup provider manager
    manager = MultiProviderLLMManager()
    
    # Add services (use mock for demo - replace with real API keys)
    manager.add_mock_service("Mock GPT", delay=0.5)
    manager.add_mock_service("Mock Claude", delay=0.8)
    manager.add_mock_service("Mock Gemini", delay=0.3)
    
    # For real usage:
    # manager.add_openai_service(os.getenv("OPENAI_API_KEY"), "OpenAI")
    # manager.add_anthropic_service(os.getenv("ANTHROPIC_API_KEY"), "Claude")
    
    # Start all services
    await manager.start_all()
    
    # Give services time to register with cluster
    await asyncio.sleep(2)
    
    print("\n✅ All LLM provider services running")
    print("   Now workflows can use any provider seamlessly!")
    
    # Cleanup
    await manager.stop_all()


async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="External LLM Provider Services")
    parser.add_argument("--provider", choices=["openai", "anthropic", "mock", "all"], 
                       default="mock", help="LLM provider to start")
    parser.add_argument("--openai-key", help="OpenAI API key")
    parser.add_argument("--anthropic-key", help="Anthropic API key")
    parser.add_argument("--server", default="http://localhost:8000", help="Cluster URL")
    
    args = parser.parse_args()
    
    if args.provider == "openai":
        if not args.openai_key:
            print("❌ OpenAI API key required: --openai-key YOUR_KEY")
            return
        
        service = OpenAIService(api_key=args.openai_key, cluster_url=args.server)
        await service.start()
        
    elif args.provider == "anthropic":
        if not args.anthropic_key:
            print("❌ Anthropic API key required: --anthropic-key YOUR_KEY")
            return
        
        service = AnthropicService(api_key=args.anthropic_key, cluster_url=args.server)
        await service.start()
        
    elif args.provider == "mock":
        await demo_multi_provider()
        
    elif args.provider == "all":
        manager = MultiProviderLLMManager()
        
        if args.openai_key:
            manager.add_openai_service(args.openai_key)
        if args.anthropic_key:
            manager.add_anthropic_service(args.anthropic_key)
        
        # Always add mock for testing
        manager.add_mock_service()
        
        await manager.start_all()
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            await manager.stop_all()


if __name__ == "__main__":
    print("""
🌐 External LLM Provider Services

This module provides Socket.IO services for external LLM providers:
- OpenAI (GPT models)
- Anthropic (Claude models)  
- Mock service for testing

Usage:
  python services/external_llm_providers.py --provider openai --openai-key YOUR_KEY
  python services/external_llm_providers.py --provider anthropic --anthropic-key YOUR_KEY
  python services/external_llm_providers.py --provider mock  # For testing
  python services/external_llm_providers.py --provider all   # Start all available
    """)
    
    asyncio.run(main())