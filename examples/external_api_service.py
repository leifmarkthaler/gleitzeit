#!/usr/bin/env python3
"""
Example External API Service

Demonstrates a simple external service that handles API integration tasks.
Shows how any service can integrate with Gleitzeit via Socket.IO.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Dict, Any

# Add the parent directory to the path so we can import gleitzeit_cluster
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.external_service_node import ExternalServiceNode, ExternalServiceCapability


class MockAPIService:
    """Mock API service for demonstration"""
    
    def __init__(self):
        self.api_endpoints = {
            '/ml-results': self.handle_ml_results,
            '/notify': self.handle_notification,
            '/login': self.handle_login,
            '/users': self.handle_get_users,
            '/deploy': self.handle_deployment
        }
        
    async def handle_api_request(self, task_data: dict) -> dict:
        """Handle generic API request"""
        print(f"🌐 Processing API request...")
        
        parameters = task_data.get('parameters', {})
        external_params = parameters.get('external_parameters', {})
        
        endpoint = external_params.get('endpoint', '/unknown')
        method = external_params.get('method', 'GET')
        payload = external_params.get('payload', {})
        headers = external_params.get('headers', {})
        
        print(f"   {method} {endpoint}")
        print(f"   Payload: {json.dumps(payload, indent=2)[:200]}...")
        
        # Route to specific handler
        handler = self.api_endpoints.get(endpoint, self.handle_generic_endpoint)
        
        # Simulate network delay
        await asyncio.sleep(0.5)
        
        return await handler(method, payload, headers)
    
    async def handle_ml_results(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle ML results notification"""
        print(f"   📊 Received ML results notification")
        
        model_accuracy = payload.get('model_accuracy', 'unknown')
        inference_count = payload.get('inference_count', 0)
        analysis_summary = payload.get('analysis_summary', {})
        
        print(f"   Model Accuracy: {model_accuracy}")
        print(f"   Inference Count: {inference_count}")
        print(f"   Analysis: {analysis_summary}")
        
        return {
            'status': 'success',
            'message': 'ML results received and processed',
            'received_at': time.time(),
            'processed_fields': len(payload)
        }
    
    async def handle_notification(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle notification request"""
        print(f"   🔔 Sending notification")
        
        processed_count = payload.get('processed_count', 0)
        print(f"   Notifying about {processed_count} processed items")
        
        return {
            'status': 'notification_sent',
            'notification_id': f"notif_{int(time.time())}",
            'recipients': ['admin@example.com'],
            'sent_at': time.time()
        }
    
    async def handle_login(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle authentication request"""
        print(f"   🔐 Processing authentication")
        
        return {
            'status': 'authenticated',
            'token': f"token_{int(time.time())}",
            'expires_in': 3600,
            'user_id': 'demo_user'
        }
    
    async def handle_get_users(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle get users request"""
        print(f"   👥 Fetching user data")
        
        # Check for auth token
        auth_header = headers.get('Authorization', '')
        if not auth_header.startswith('token_'):
            return {'error': 'Invalid authentication token'}
        
        return {
            'users': [
                {'id': 1, 'name': 'Alice', 'role': 'admin'},
                {'id': 2, 'name': 'Bob', 'role': 'user'},
                {'id': 3, 'name': 'Charlie', 'role': 'user'}
            ],
            'total_count': 3,
            'fetched_at': time.time()
        }
    
    async def handle_deployment(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle model deployment request"""
        print(f"   🚀 Deploying model")
        
        model_id = payload.get('model_id', 'unknown')
        print(f"   Deploying model: {model_id}")
        
        # Simulate deployment time
        await asyncio.sleep(2)
        
        return {
            'status': 'deployed',
            'model_id': model_id,
            'deployment_url': f'https://api.example.com/models/{model_id}',
            'deployed_at': time.time()
        }
    
    async def handle_generic_endpoint(self, method: str, payload: dict, headers: dict) -> dict:
        """Handle unknown endpoint"""
        print(f"   ❓ Unknown endpoint, returning generic response")
        
        return {
            'status': 'ok',
            'message': 'Generic API response',
            'method': method,
            'payload_size': len(json.dumps(payload)),
            'timestamp': time.time()
        }


async def main():
    """Main entry point for external API service"""
    print("🌐 Starting External API Service")
    print("=" * 50)
    
    # Create API service instance
    api_service = MockAPIService()
    
    # Create external service node
    service_node = ExternalServiceNode(
        service_name="Mock API Service",
        cluster_url="http://localhost:8000",
        capabilities=[
            ExternalServiceCapability.API_INTEGRATION,
            ExternalServiceCapability.CUSTOM_PROCESSING
        ],
        max_concurrent_tasks=10,
        heartbeat_interval=20
    )
    
    # Register task handlers
    service_node.register_task_handler("api_integration", api_service.handle_api_request)
    service_node.register_task_handler("external_api", api_service.handle_api_request)
    service_node.register_task_handler("custom_processing", api_service.handle_api_request)
    
    print("📋 Registered API endpoints:")
    for endpoint in api_service.api_endpoints.keys():
        print(f"   - {endpoint}")
    
    print("🔧 Registered task handlers:")
    print("   - api_integration")
    print("   - external_api") 
    print("   - custom_processing")
    
    try:
        print(f"\\n🔌 Connecting to Gleitzeit cluster at http://localhost:8000")
        await service_node.start()
    except KeyboardInterrupt:
        print("\\n🛑 Interrupted by user")
    except Exception as e:
        print(f"💥 Service failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\\n🧹 Cleaning up...")
        await service_node.stop()


if __name__ == "__main__":
    print("💡 Run alongside the ML service for complete external task demo:")
    print("   Terminal 1: python examples/monitoring_demo.py")
    print("   Terminal 2: python examples/external_ml_service.py")
    print("   Terminal 3: python examples/external_api_service.py")
    print("   Terminal 4: python examples/external_task_demo.py")
    print()
    
    asyncio.run(main())