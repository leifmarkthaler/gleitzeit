#!/usr/bin/env python3
"""
Test script to check if API endpoints are properly registered
"""

import sys
sys.path.insert(0, 'src')

from gleitzeit.api.main import app

print("=== Registered API Routes ===\n")

# Get all routes
for route in app.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        for method in route.methods:
            print(f"{method:6} {route.path}")

print("\n=== Checking for list endpoints ===\n")

# Check specifically for our endpoints
has_get_workflows = False
has_get_tasks = False

for route in app.routes:
    if hasattr(route, 'path') and hasattr(route, 'methods'):
        if route.path == "/workflows" and "GET" in route.methods:
            has_get_workflows = True
            print(f"✓ Found GET /workflows - handler: {route.endpoint.__name__ if hasattr(route, 'endpoint') else 'unknown'}")
        if route.path == "/tasks" and "GET" in route.methods:
            has_get_tasks = True
            print(f"✓ Found GET /tasks - handler: {route.endpoint.__name__ if hasattr(route, 'endpoint') else 'unknown'}")

if not has_get_workflows:
    print("✗ GET /workflows NOT FOUND")
if not has_get_tasks:
    print("✗ GET /tasks NOT FOUND")

print(f"\nTotal routes: {len(app.routes)}")