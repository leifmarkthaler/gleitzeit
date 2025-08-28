#!/usr/bin/env python3
"""
Minimal test to check if GET /workflows works
"""

from fastapi import FastAPI, Query
from typing import Optional
import uvicorn

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Test API"}

@app.get("/workflows")
async def list_workflows(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, le=100, description="Maximum results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip")
):
    """List all workflows with optional filtering"""
    return {
        "workflows": [],
        "total": 0,
        "limit": limit,
        "offset": offset,
        "message": "GET /workflows works!"
    }

@app.post("/workflows")
async def create_workflow():
    return {"message": "POST /workflows works"}

@app.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    return {"workflow_id": workflow_id, "message": "GET /workflows/{id} works"}

if __name__ == "__main__":
    print("Starting minimal test API on port 8002...")
    print("Routes:")
    for route in app.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            for method in route.methods:
                print(f"  {method:6} {route.path}")
    
    uvicorn.run(app, host="0.0.0.0", port=8002)