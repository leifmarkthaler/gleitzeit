#!/usr/bin/env python3
"""
Debug script to test the actual API with GET /workflows
"""

import sys
import asyncio
sys.path.insert(0, 'src')

from gleitzeit.api.main import app
import uvicorn
from fastapi.testclient import TestClient

# Create test client
client = TestClient(app)

print("=== Testing with TestClient ===")

# Test GET /workflows
print("\nTesting GET /workflows:")
response = client.get("/workflows")
print(f"Status: {response.status_code}")
print(f"Response: {response.json()}")

# Test POST /workflows
print("\nTesting POST /workflows:")
response = client.post("/workflows", json={
    "name": "Test Workflow",
    "tasks": [{"name": "Test Task", "protocol": "python/v1", "method": "python/execute", "params": {}}]
})
print(f"Status: {response.status_code}")
if response.status_code == 200:
    print(f"Response: {response.json()}")
else:
    print(f"Error: {response.text}")

print("\n=== Starting actual server on port 8003 ===")
print("After server starts, test with:")
print("  curl http://localhost:8003/workflows")
print()

# Run the actual server
uvicorn.run(app, host="0.0.0.0", port=8003, log_level="info")