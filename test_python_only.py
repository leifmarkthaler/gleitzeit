#!/usr/bin/env python3
"""Test Python provider in detail"""

import asyncio
import sys
from pathlib import Path
import tempfile
import json

sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client
from gleitzeit.client import ClientMode

async def main():
    workflow = {
        "name": "Python Test",
        "tasks": [
            {
                "id": "task1",
                "method": "python/execute",
                "parameters": {
                    "file": "examples/scripts/generate_numbers.py"
                }
            }
        ]
    }
    
    async with Client(mode=ClientMode.NATIVE) as client:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(workflow, f)
            workflow_file = f.name
        
        results = await client.run_workflow(workflow_file)
        print(f"Full results: {json.dumps(results, indent=2)}")

asyncio.run(main())