#!/usr/bin/env python3
"""
Test script for validation task flow
"""

import asyncio
import json
import yaml
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import Gleitzeit components
from gleitzeit.handlers import discover_handlers
from gleitzeit.handlers.validation import ValidationHandler
from gleitzeit.handlers.python import PythonHandler
from gleitzeit.core.models import Task, TaskStatus


async def test_validation_handler():
    """Test the ValidationHandler directly"""
    logger.info("Testing ValidationHandler...")

    # Discover all handlers
    handlers = discover_handlers()
    logger.info(f"Discovered handlers: {list(handlers.keys())}")

    # Create validation handler
    validation_handler = ValidationHandler()

    # Test 1: Simple evaluation that passes
    task1 = Task(
        id="test_validation_1",
        name="test_validation_pass",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {"expression": "value > 50", "name": "threshold_check"}
            ],
            "mode": "all",
            "on_failure": "skip",
            "context": {"value": 75}
        }
    )

    result1 = await validation_handler.execute(task1)
    logger.info(f"Test 1 (should pass): {result1.result}")
    assert result1.result['valid'] == True
    assert result1.status == TaskStatus.COMPLETED

    # Test 2: Simple evaluation that fails
    task2 = Task(
        id="test_validation_2",
        name="test_validation_fail",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {"expression": "value > 50", "name": "threshold_check"}
            ],
            "mode": "all",
            "on_failure": "skip",
            "context": {"value": 25}
        }
    )

    result2 = await validation_handler.execute(task2)
    logger.info(f"Test 2 (should fail): {result2.result}")
    assert result2.result['valid'] == False
    assert result2.status == TaskStatus.COMPLETED

    # Test 3: Multiple conditions with "any" mode
    task3 = Task(
        id="test_validation_3",
        name="test_validation_any",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {"expression": "value > 100", "name": "high_threshold"},
                {"expression": "value < 30", "name": "low_threshold"}
            ],
            "mode": "any",
            "context": {"value": 25}
        }
    )

    result3 = await validation_handler.execute(task3)
    logger.info(f"Test 3 (any mode, should pass): {result3.result}")
    assert result3.result['valid'] == True  # Passes because 25 < 30

    # Test 4: Assert that fails
    task4 = Task(
        id="test_validation_4",
        name="test_assertion",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/assert",
        params={
            "assertions": [
                {"expression": "value > 0", "name": "positive_check"},
                {"expression": "value < 10", "name": "range_check"}
            ],
            "context": {"value": 15}
        }
    )

    result4 = await validation_handler.execute(task4)
    logger.info(f"Test 4 (assertion, should fail): {result4.status}, {result4.error}")
    assert result4.status == TaskStatus.FAILED  # Fails because 15 is not < 10

    # Test 5: Gate control
    task5 = Task(
        id="test_validation_5",
        name="test_gate",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/gate",
        params={
            "rules": [
                {
                    "name": "premium_route",
                    "condition": "total > 1000",
                    "enable_tasks": ["premium_process"],
                    "disable_tasks": ["standard_process"]
                }
            ],
            "context": {"total": 1500}
        }
    )

    result5 = await validation_handler.execute(task5)
    logger.info(f"Test 5 (gate): {result5.result}")
    assert "premium_process" in result5.result['control']['enable_tasks']
    assert "standard_process" in result5.result['control']['skip_tasks']

    logger.info("All ValidationHandler tests passed!")


async def test_integration():
    """Test the integration with Python handler"""
    logger.info("\nTesting integration with PythonHandler...")

    python_handler = PythonHandler()
    validation_handler = ValidationHandler()

    # Step 1: Generate data with Python handler
    generate_task = Task(
        id="gen_1",
        name="generate_data",
        workflow_id="test_workflow",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": "result = {'value': 75, 'status': 'success'}"
        }
    )

    gen_result = await python_handler.execute(generate_task)
    logger.info(f"Generated data: {gen_result.result}")

    # Step 2: Validate the data
    validate_task = Task(
        id="val_1",
        name="validate_data",
        workflow_id="test_workflow",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {"expression": "value > 50", "name": "value_check"},
                {"expression": "status == 'success'", "name": "status_check"}
            ],
            "mode": "all",
            "context": gen_result.result
        }
    )

    val_result = await validation_handler.execute(validate_task)
    logger.info(f"Validation result: {val_result.result}")

    # Step 3: Process if valid
    if val_result.result['valid']:
        process_task = Task(
            id="proc_1",
            name="process_data",
            workflow_id="test_workflow",
            protocol="python/v1",
            method="python/execute",
            params={
                "code": f"result = {{'processed_value': {gen_result.result['value']} * 2}}"
            }
        )

        proc_result = await python_handler.execute(process_task)
        logger.info(f"Processed data: {proc_result.result}")
    else:
        logger.info("Skipping processing due to validation failure")

    logger.info("Integration test completed!")


async def main():
    """Main test function"""
    try:
        await test_validation_handler()
        await test_integration()
        logger.info("\n✅ All tests passed successfully!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())