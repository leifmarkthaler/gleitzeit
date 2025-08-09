#!/usr/bin/env python3
"""
Internal LLM Executor Service

Wraps Ollama endpoint management as a Socket.IO service.
This allows LLM tasks to be handled through the unified Socket.IO architecture
while maintaining all existing Ollama functionality.
"""

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.external_service_node import (
    ExternalServiceNode,
    ExternalServiceCapability
)
from gleitzeit_cluster.execution.ollama_endpoint_manager import (
    OllamaEndpointManager,
    EndpointConfig,
    LoadBalancingStrategy
)
from gleitzeit_cluster.execution.ollama_client import OllamaClient


class InternalLLMService(ExternalServiceNode):
    """
    Internal LLM service that wraps Ollama endpoint management.
    
    Provides LLM execution via Socket.IO while maintaining all existing
    Ollama features: load balancing, endpoint management, model loading, etc.
    """
    
    def __init__(
        self,
        service_name: str = "Internal LLM Service",
        cluster_url: str = "http://localhost:8000",
        ollama_url: str = "http://localhost:11434",
        ollama_endpoints: Optional[List[EndpointConfig]] = None,
        load_balancing_strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
        max_concurrent_tasks: int = 20,
        model_preload: List[str] = None
    ):
        """
        Initialize internal LLM service.
        
        Args:
            service_name: Name of this LLM service
            cluster_url: Gleitzeit cluster URL
            ollama_url: Primary Ollama endpoint URL
            ollama_endpoints: List of Ollama endpoints for load balancing
            load_balancing_strategy: Strategy for distributing requests
            max_concurrent_tasks: Maximum parallel LLM tasks
            model_preload: Models to preload on service start
        """
        super().__init__(
            service_name=service_name,
            cluster_url=cluster_url,
            capabilities=[
                ExternalServiceCapability.LLM_GENERATION,
                ExternalServiceCapability.ML_INFERENCE
            ],
            max_concurrent_tasks=max_concurrent_tasks,
            heartbeat_interval=15
        )
        
        # Initialize Ollama management (reuse existing code)
        if ollama_endpoints:
            self.ollama_manager = OllamaEndpointManager(
                endpoints=ollama_endpoints,
                strategy=load_balancing_strategy
            )
            self.use_load_balancing = True
        else:
            self.ollama_client = OllamaClient(base_url=ollama_url)
            self.use_load_balancing = False
        
        self.model_preload = model_preload or []
        
        # Register task handlers
        self.register_task_handler("llm_generation", self.execute_llm_task)
        self.register_task_handler("vision", self.execute_vision_task)
        
        # Track LLM metrics
        self.llm_metrics = {
            'total_requests': 0,
            'total_failures': 0,
            'avg_response_time': 0,
            'models_loaded': set(),
            'endpoint_health': {}
        }
    
    async def start(self):
        """Start LLM service and preload models"""
        # Initialize Ollama endpoints
        if self.use_load_balancing:
            await self.ollama_manager.initialize()
            print(f"🔗 Initialized {len(self.ollama_manager.endpoints)} Ollama endpoints")
            
            # Check endpoint health
            for endpoint in self.ollama_manager.endpoints:
                try:
                    models = await endpoint.client.list_models()
                    self.llm_metrics['endpoint_health'][endpoint.url] = {
                        'status': 'healthy',
                        'models': len(models.get('models', []))
                    }
                    print(f"   ✅ {endpoint.url}: {len(models.get('models', []))} models")
                except Exception as e:
                    self.llm_metrics['endpoint_health'][endpoint.url] = {
                        'status': 'unhealthy',
                        'error': str(e)
                    }
                    print(f"   ❌ {endpoint.url}: {e}")
        else:
            try:
                models = await self.ollama_client.list_models()
                model_count = len(models.get('models', []))
                print(f"🔗 Connected to Ollama: {self.ollama_client.base_url} ({model_count} models)")
                self.llm_metrics['endpoint_health'][self.ollama_client.base_url] = {
                    'status': 'healthy',
                    'models': model_count
                }
            except Exception as e:
                print(f"❌ Failed to connect to Ollama: {e}")
                self.llm_metrics['endpoint_health'][self.ollama_client.base_url] = {
                    'status': 'unhealthy',
                    'error': str(e)
                }
        
        # Preload models
        if self.model_preload:
            print(f"📥 Preloading {len(self.model_preload)} models...")
            for model in self.model_preload:
                try:
                    await self._ensure_model_loaded(model)
                    self.llm_metrics['models_loaded'].add(model)
                    print(f"   ✅ Loaded: {model}")
                except Exception as e:
                    print(f"   ❌ Failed to load {model}: {e}")
        
        # Start the service
        await super().start()
    
    async def execute_llm_task(self, task_data: dict) -> dict:
        """
        Execute LLM text generation task.
        
        Handles the same parameters as the original text tasks.
        """
        start_time = time.time()
        
        try:
            # Extract parameters
            params = task_data.get('parameters', {})
            
            # Handle both external and native parameter formats
            if 'external_parameters' in params:
                # External task format
                exec_params = params['external_parameters']
                prompt = exec_params.get('prompt')
                model = exec_params.get('model', 'llama3')
                temperature = exec_params.get('temperature', 0.7)
                max_tokens = exec_params.get('max_tokens')
            else:
                # Native task format
                prompt = params.get('prompt')
                model = params.get('model_name', params.get('model', 'llama3'))
                temperature = params.get('temperature', 0.7)
                max_tokens = params.get('max_tokens')
            
            if not prompt:
                raise ValueError("No prompt provided")
            
            print(f"🧠 Executing LLM task: {model}")
            print(f"   Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
            
            # Ensure model is loaded
            await self._ensure_model_loaded(model)
            
            # Generate response using appropriate endpoint
            if self.use_load_balancing:
                endpoint = await self.ollama_manager.get_best_endpoint()
                client = endpoint.client
            else:
                client = self.ollama_client
            
            # Execute generation
            response = await client.generate(
                model=model,
                prompt=prompt,
                options={
                    'temperature': temperature,
                    'num_predict': max_tokens
                } if max_tokens else {'temperature': temperature}
            )
            
            # Extract response text
            if isinstance(response, dict):
                result_text = response.get('response', str(response))
            else:
                result_text = str(response)
            
            # Update metrics
            execution_time = time.time() - start_time
            self.llm_metrics['total_requests'] += 1
            self._update_avg_response_time(execution_time)
            
            print(f"✅ LLM task completed in {execution_time:.2f}s")
            print(f"   Response: {result_text[:100]}{'...' if len(result_text) > 100 else ''}")
            
            return {
                'success': True,
                'result': result_text,
                'model': model,
                'execution_time': execution_time,
                'endpoint': client.base_url if hasattr(client, 'base_url') else 'unknown'
            }
            
        except Exception as e:
            self.llm_metrics['total_failures'] += 1
            error_msg = f"LLM execution failed: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                'success': False,
                'error': error_msg,
                'traceback': traceback.format_exc(),
                'execution_time': time.time() - start_time
            }
    
    async def execute_vision_task(self, task_data: dict) -> dict:
        """Execute vision/image analysis task"""
        start_time = time.time()
        
        try:
            params = task_data.get('parameters', {})
            
            if 'external_parameters' in params:
                exec_params = params['external_parameters']
                prompt = exec_params.get('prompt')
                image_path = exec_params.get('image_path')
                model = exec_params.get('model', 'llava')
            else:
                prompt = params.get('prompt')
                image_path = params.get('image_path')
                model = params.get('model_name', params.get('model', 'llava'))
            
            if not prompt or not image_path:
                raise ValueError("Both prompt and image_path required for vision tasks")
            
            print(f"👁️ Executing vision task: {model}")
            print(f"   Image: {image_path}")
            
            # Use appropriate endpoint
            if self.use_load_balancing:
                endpoint = await self.ollama_manager.get_best_endpoint()
                client = endpoint.client
            else:
                client = self.ollama_client
            
            # Execute vision task
            response = await client.generate_with_image(
                model=model,
                prompt=prompt,
                image_path=image_path
            )
            
            execution_time = time.time() - start_time
            self.llm_metrics['total_requests'] += 1
            
            return {
                'success': True,
                'result': response.get('response', str(response)),
                'model': model,
                'execution_time': execution_time
            }
            
        except Exception as e:
            self.llm_metrics['total_failures'] += 1
            return {
                'success': False,
                'error': str(e),
                'execution_time': time.time() - start_time
            }
    
    async def _ensure_model_loaded(self, model: str):
        """Ensure model is loaded on appropriate endpoint"""
        try:
            if self.use_load_balancing:
                # Try to find an endpoint with the model already loaded
                for endpoint in self.ollama_manager.endpoints:
                    try:
                        models = await endpoint.client.list_models()
                        model_names = [m['name'] for m in models.get('models', [])]
                        if model in model_names:
                            return  # Model already loaded
                    except:
                        continue
                
                # Load on best endpoint
                best_endpoint = await self.ollama_manager.get_best_endpoint()
                await best_endpoint.client.pull_model(model)
            else:
                # Single endpoint - just ensure model exists
                await self.ollama_client.pull_model(model)
                
        except Exception as e:
            print(f"⚠️ Model loading warning for {model}: {e}")
            # Continue anyway - model might be available
    
    def _update_avg_response_time(self, new_time: float):
        """Update average response time metric"""
        total = self.llm_metrics['total_requests']
        if total == 1:
            self.llm_metrics['avg_response_time'] = new_time
        else:
            avg = self.llm_metrics['avg_response_time']
            self.llm_metrics['avg_response_time'] = (
                (avg * (total - 1) + new_time) / total
            )
    
    def get_status(self) -> dict:
        """Get service status including LLM metrics"""
        status = super().get_status()
        status.update({
            'llm_metrics': self.llm_metrics,
            'use_load_balancing': self.use_load_balancing,
            'endpoints': len(self.ollama_manager.endpoints) if self.use_load_balancing else 1,
            'models_loaded': list(self.llm_metrics['models_loaded'])
        })
        return status


async def main():
    """Main entry point for internal LLM service"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Internal LLM Service")
    parser.add_argument("--name", default="Internal LLM Service", help="Service name")
    parser.add_argument("--server", default="http://localhost:8000", help="Cluster URL")
    parser.add_argument("--ollama", default="http://localhost:11434", help="Ollama URL")
    parser.add_argument("--workers", type=int, default=20, help="Max concurrent tasks")
    parser.add_argument("--preload", nargs="*", help="Models to preload")
    parser.add_argument("--endpoints", nargs="*", help="Additional Ollama endpoints")
    
    args = parser.parse_args()
    
    print("🧠 Starting Internal LLM Service")
    print("=" * 50)
    print(f"📝 Service Name: {args.name}")
    print(f"🔗 Cluster URL: {args.server}")
    print(f"🤖 Ollama URL: {args.ollama}")
    print(f"👥 Max Workers: {args.workers}")
    if args.preload:
        print(f"📥 Preload Models: {', '.join(args.preload)}")
    print()
    
    # Setup endpoints
    ollama_endpoints = None
    if args.endpoints:
        ollama_endpoints = [EndpointConfig(args.ollama, priority=1)]
        for i, endpoint_url in enumerate(args.endpoints):
            ollama_endpoints.append(EndpointConfig(endpoint_url, priority=i+2))
        print(f"🔗 Using {len(ollama_endpoints)} Ollama endpoints")
    
    # Create and start LLM service
    llm_service = InternalLLMService(
        service_name=args.name,
        cluster_url=args.server,
        ollama_url=args.ollama,
        ollama_endpoints=ollama_endpoints,
        max_concurrent_tasks=args.workers,
        model_preload=args.preload or []
    )
    
    try:
        print(f"🔌 Connecting to Gleitzeit cluster at {args.server}")
        await llm_service.start()
    except KeyboardInterrupt:
        print("\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Service failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n🧹 Cleaning up...")
        await llm_service.stop()


if __name__ == "__main__":
    asyncio.run(main())