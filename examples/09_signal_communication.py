#!/usr/bin/env python3
"""
Signal Communication Example
=============================
This example demonstrates signal-based communication between tasks.

Signals enable:
- Internal workflow coordination
- Cross-workflow communication
- Event-driven orchestration
- Waiting for external events

Prerequisites:
- Gleitzeit server running: gleitzeit serve --dev-mode
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """Run signal communication example"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Workflow demonstrating signal broadcast pattern
        workflow = {
            'name': 'signal-example',
            'tasks': [
                # Step 1: Initialize
                {
                    'id': 'initialize',
                    'type': 'python',
                    'params': {
                        'code': '''
import datetime
result = {
    "started_at": datetime.datetime.now().isoformat(),
    "status": "initialized"
}
print("Workflow initialized")
'''
                    }
                },
                # Step 2: Process data
                {
                    'id': 'process_data',
                    'type': 'python',
                    'depends_on': ['initialize'],
                    'params': {
                        'code': '''
print("Processing data")
result = {"processed_items": 100, "status": "completed"}
'''
                    }
                },
                # Step 3: Send completion signal
                {
                    'id': 'send_signal',
                    'type': 'signal',
                    'method': 'signal/send',
                    'depends_on': ['process_data'],
                    'params': {
                        'signal_name': 'processing-complete',
                        'payload': {
                            'items_processed': 100,
                            'status': 'success'
                        }
                    }
                },
                # Step 4: Broadcast to all workflows
                {
                    'id': 'broadcast_completion',
                    'type': 'signal',
                    'method': 'signal/broadcast',
                    'depends_on': ['send_signal'],
                    'params': {
                        'signal_name': 'workflow-completed',
                        'payload': {
                            'workflow_type': 'signal-example',
                            'success': True
                        }
                    }
                }
            ]
        }

        # Submit workflow
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted signal workflow: {response.workflow_id}")

        # Wait for completion
        print("\n⏳ Running signal-based workflow...")
        print("   - Sending internal signal")
        print("   - Waiting for signal")
        print("   - Processing data")
        print("   - Broadcasting completion")

        status = await client.wait_for_workflow(response.workflow_id, timeout=60)

        print(f"\n✓ Signal workflow completed: {status.status}")
        print(f"   All signal operations successful!")


if __name__ == "__main__":
    print("=" * 60)
    print("Signal Communication Example")
    print("=" * 60)
    print()

    asyncio.run(main())
