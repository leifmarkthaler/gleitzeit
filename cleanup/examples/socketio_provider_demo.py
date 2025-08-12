#!/usr/bin/env python3
"""
Socket.IO Provider Demo

Demonstrates the Socket.IO-based provider system for Gleitzeit.
This replaces the MCP stdio-based approach with Socket.IO for consistency.
"""

import asyncio
import logging
from typing import Any, Dict, List

from gleitzeit_extensions.socketio_provider_client import (
    SocketIOProviderClient,
    OpenAIProvider,
    ToolProvider
)
from gleitzeit_extensions.socketio_provider_manager import SocketIOProviderManager
from gleitzeit_cluster.communication.socketio_server import SocketIOServer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# === Custom Provider Example ===

class CustomLLMProvider(SocketIOProviderClient):
    """Example custom LLM provider"""
    
    def __init__(self, **kwargs):
        super().__init__(
            name="custom-llm",
            provider_type="llm",
            models=["custom-7b", "custom-13b", "custom-70b"],
            capabilities=["text", "code", "streaming"],
            description="Custom LLM models",
            **kwargs
        )
        self.request_count = 0
    
    async def invoke(self, method: str, **kwargs) -> Any:
        self.request_count += 1
        
        if method == "complete":
            prompt = kwargs.get('prompt', '')
            model = kwargs.get('model', 'custom-7b')
            return {
                "response": f"[{model}] Response to: {prompt}",
                "tokens": len(prompt.split()),
                "request_number": self.request_count
            }
        elif method == "analyze_code":
            code = kwargs.get('code', '')
            return {
                "language": "python",
                "complexity": "medium",
                "lines": len(code.split('\n'))
            }
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def generate(self, prompt: str, model: str = "custom-7b", **kwargs):
        """Generate text"""
        result = await self.invoke("complete", prompt=prompt, model=model, **kwargs)
        return result["response"]
    
    async def stream(self, prompt: str, model: str = "custom-7b", **kwargs):
        """Stream responses token by token"""
        response = f"[{model}] Streaming response to: {prompt}"
        for token in response.split():
            yield {"token": token, "done": False}
            await asyncio.sleep(0.05)  # Simulate token generation time
        yield {"token": "", "done": True}
    
    async def get_health_status(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "request_count": self.request_count,
            "models": self.models
        }


class DatabaseProvider(SocketIOProviderClient):
    """Example database provider"""
    
    def __init__(self, **kwargs):
        super().__init__(
            name="database",
            provider_type="tool",
            capabilities=["sql", "query", "storage"],
            description="Database operations provider",
            **kwargs
        )
        # In-memory mock database
        self.data = {
            "users": [
                {"id": 1, "name": "Alice", "role": "admin"},
                {"id": 2, "name": "Bob", "role": "user"},
                {"id": 3, "name": "Charlie", "role": "user"}
            ],
            "products": [
                {"id": 1, "name": "Widget", "price": 9.99},
                {"id": 2, "name": "Gadget", "price": 19.99}
            ]
        }
    
    async def invoke(self, method: str, **kwargs) -> Any:
        if method == "query":
            table = kwargs.get('table', 'users')
            filters = kwargs.get('filters', {})
            
            if table not in self.data:
                raise ValueError(f"Table '{table}' not found")
            
            results = self.data[table]
            
            # Apply simple filters
            if filters:
                filtered = []
                for item in results:
                    match = all(
                        item.get(key) == value 
                        for key, value in filters.items()
                    )
                    if match:
                        filtered.append(item)
                results = filtered
            
            return {"results": results, "count": len(results)}
            
        elif method == "insert":
            table = kwargs.get('table', 'users')
            record = kwargs.get('record', {})
            
            if table not in self.data:
                self.data[table] = []
            
            # Generate ID
            max_id = max([r.get('id', 0) for r in self.data[table]], default=0)
            record['id'] = max_id + 1
            
            self.data[table].append(record)
            return {"success": True, "id": record['id']}
            
        else:
            raise ValueError(f"Unknown method: {method}")
    
    async def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "query",
                "description": "Query database table",
                "parameters": {
                    "table": {"type": "string", "description": "Table name"},
                    "filters": {"type": "object", "description": "Filter conditions"}
                }
            },
            {
                "name": "insert",
                "description": "Insert record into table",
                "parameters": {
                    "table": {"type": "string", "description": "Table name"},
                    "record": {"type": "object", "description": "Record to insert"}
                }
            }
        ]
    
    async def get_health_status(self) -> Dict[str, Any]:
        total_records = sum(len(records) for records in self.data.values())
        return {
            "healthy": True,
            "tables": list(self.data.keys()),
            "total_records": total_records
        }


# === Demo Functions ===

async def start_server_with_providers():
    """Start Socket.IO server with provider manager"""
    print("🚀 Starting Socket.IO server with provider support...")
    
    # Create Socket.IO server
    server = SocketIOServer(
        host="0.0.0.0",
        port=8000,
        cors_allowed_origins="*"
    )
    
    # Create and attach provider manager BEFORE starting server
    provider_manager = SocketIOProviderManager()
    provider_manager.attach_to_server(server.sio)
    
    # Start server (namespace handlers are now registered)
    await server.start()
    
    # Start health monitoring
    health_task = asyncio.create_task(provider_manager.monitor_health())
    
    return server, provider_manager, health_task


async def start_providers():
    """Start example provider clients"""
    print("\n📡 Starting provider clients...")
    
    providers = []
    
    # Start Custom LLM Provider
    custom_llm = CustomLLMProvider(server_url="http://localhost:8000")
    task1 = asyncio.create_task(custom_llm.run())
    providers.append((custom_llm, task1))
    
    # Start Calculator Tool Provider
    calculator = ToolProvider(server_url="http://localhost:8000")
    task2 = asyncio.create_task(calculator.run())
    providers.append((calculator, task2))
    
    # Start Database Provider
    database = DatabaseProvider(server_url="http://localhost:8000")
    task3 = asyncio.create_task(database.run())
    providers.append((database, task3))
    
    # Wait for all providers to connect
    await asyncio.sleep(2)
    
    return providers


async def test_provider_operations(provider_manager: SocketIOProviderManager):
    """Test various provider operations"""
    print("\n🧪 Testing provider operations...")
    
    # List all providers
    print("\n📋 Connected Providers:")
    all_providers = provider_manager.get_all_providers()
    for name, info in all_providers.items():
        print(f"  - {name} ({info['type']})")
        print(f"    Models: {info.get('models', [])}")
        print(f"    Capabilities: {info.get('capabilities', [])}")
    
    # Test model routing
    print("\n🎯 Model Routing:")
    test_models = ["custom-7b", "custom-13b", "gpt-4", "unknown-model"]
    for model in test_models:
        provider = provider_manager.find_provider_for_model(model)
        if provider:
            print(f"  {model} → {provider}")
        else:
            print(f"  {model} → No provider found")
    
    # Test capability discovery
    print("\n🔍 Capability Discovery:")
    test_capabilities = ["text", "code", "sql", "math", "vision"]
    for capability in test_capabilities:
        providers = provider_manager.find_providers_by_capability(capability)
        if providers:
            print(f"  {capability}: {', '.join(providers)}")
        else:
            print(f"  {capability}: No providers")
    
    # Test LLM invocation
    print("\n💬 LLM Invocation:")
    try:
        result = await provider_manager.invoke_provider(
            "custom-llm",
            "complete",
            prompt="Hello, world!",
            model="custom-7b"
        )
        print(f"  Response: {result}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # Test tool invocation
    print("\n🔧 Tool Invocation:")
    try:
        result = await provider_manager.invoke_provider(
            "calculator",
            "add",
            a=10,
            b=20
        )
        print(f"  10 + 20 = {result}")
    except Exception as e:
        print(f"  Error: {e}")
    
    # Test database operations
    print("\n💾 Database Operations:")
    try:
        # Query users
        result = await provider_manager.invoke_provider(
            "database",
            "query",
            table="users",
            filters={"role": "user"}
        )
        print(f"  Users with role='user': {result['count']}")
        
        # Insert new product
        result = await provider_manager.invoke_provider(
            "database",
            "insert",
            table="products",
            record={"name": "NewProduct", "price": 29.99}
        )
        print(f"  Inserted product with ID: {result['id']}")
    except Exception as e:
        print(f"  Error: {e}")


async def main():
    """Main demo function"""
    print("=" * 60)
    print("🎯 Gleitzeit Socket.IO Provider System Demo")
    print("=" * 60)
    
    server = None
    provider_manager = None
    health_task = None
    providers = []
    
    try:
        # Start server with provider manager
        server, provider_manager, health_task = await start_server_with_providers()
        
        # Give server time to start
        await asyncio.sleep(1)
        
        # Start provider clients
        providers = await start_providers()
        
        # Test provider operations
        await test_provider_operations(provider_manager)
        
        print("\n✅ Demo completed successfully!")
        print("\n📊 Final Statistics:")
        print(f"  Connected providers: {len(provider_manager.providers)}")
        print(f"  Provider rooms: {len(provider_manager.provider_rooms)}")
        print(f"  Model routes cached: {len(provider_manager._model_routing)}")
        
        print("\n⏳ Server will continue running. Press Ctrl+C to stop.")
        
        # Keep running
        await asyncio.Event().wait()
        
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down...")
    finally:
        # Cleanup
        for provider, task in providers:
            await provider.disconnect()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        if health_task:
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass
        
        if server:
            await server.stop()
        
        print("👋 Goodbye!")


if __name__ == "__main__":
    asyncio.run(main())