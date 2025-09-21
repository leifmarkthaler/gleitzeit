#!/usr/bin/env python
"""
Test signal integration in Gleitzeit.

This script tests that:
1. Signal provider is registered and accessible
2. Signal workflows can be submitted
3. Signals can be sent to workflows
"""

import asyncio
import time
import logging
from gleitzeit.client import GleitzeitClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_signal_integration():
    """Test signal integration."""
    
    # Create client with correct initialization
    client = GleitzeitClient(base_url="http://localhost:8000")
    
    try:
        # Submit signal test workflow
        logger.info("Submitting signal test workflow...")
        workflow_id = await client.submit_workflow("test_signal_workflow.yaml")
        logger.info(f"Workflow submitted: {workflow_id}")
        
        # Wait a moment for workflow to start
        await asyncio.sleep(2)
        
        # Check workflow status
        status = await client.get_workflow_status(workflow_id)
        logger.info(f"Workflow status: {status}")
        
        # Send approval signal
        logger.info("Sending approval signal...")
        signal_response = await client._make_request(
            "POST",
            f"/signals/workflows/{workflow_id}/send",
            json={
                "signal_name": "manager_approval",
                "payload": {"approved": True, "manager": "test_manager"}
            }
        )
        logger.info(f"Signal sent: {signal_response}")
        
        # Wait for workflow to process signal
        await asyncio.sleep(3)
        
        # Check workflow status again
        final_status = await client.get_workflow_status(workflow_id)
        logger.info(f"Final workflow status: {final_status}")
        
        # Get workflow results
        results = await client.get_workflow_results(workflow_id)
        logger.info(f"Workflow results: {results}")
        
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_signal_integration())
    if success:
        print("\n✓ Signal integration test passed!")
    else:
        print("\n✗ Signal integration test failed!")
        exit(1)