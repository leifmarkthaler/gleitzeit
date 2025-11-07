#!/usr/bin/env python3
"""
Test XOR pattern with validation tasks
"""

import asyncio
import json
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
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers.validation import ValidationHandler
from gleitzeit.handlers.python import PythonHandler
from gleitzeit.core.models import Task, TaskStatus


async def test_xor_with_context():
    """Test XOR pattern with proper context handling"""
    logger.info("Testing XOR pattern with validation tasks...")

    python_handler = PythonHandler()
    validation_handler = ValidationHandler()

    # Step 1: Generate payment type
    logger.info("\n1. Generating payment type...")
    payment_task = Task(
        id="payment_1",
        name="get_payment",
        workflow_id="xor_test",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
import random
payment_type = 'credit_card'  # Fixed for testing
amount = 100
result = {'payment_type': payment_type, 'amount': amount}
print(f"Payment type: {payment_type}")
"""
        }
    )

    payment_result = await python_handler.execute(payment_task)
    logger.info(f"Payment result (raw): {payment_result.result}")

    # Parse the JSON result from Python handler
    import json
    payment_data = json.loads(payment_result.result.split('\n')[-1])  # Last line is JSON result
    logger.info(f"Payment data (parsed): {payment_data}")

    # Step 2: Test validation for credit card (should pass)
    logger.info("\n2. Testing credit card validation (should pass)...")

    # Simulate what DependencyWorker would do - resolve parameters
    resolved_payment_type = payment_data['payment_type']  # 'credit_card'

    validate_cc_task = Task(
        id="val_cc",
        name="validate_credit_card",
        workflow_id="xor_test",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {
                    "expression": "payment_type == 'credit_card'",
                    "name": "is_credit_card"
                }
            ],
            "on_failure": "skip",
            "context": {
                "payment_type": resolved_payment_type  # This is the resolved value
            }
        }
    )

    cc_validation = await validation_handler.execute(validate_cc_task)
    logger.info(f"Credit card validation: valid={cc_validation.result['valid']}")
    assert cc_validation.result['valid'] == True

    # Step 3: Test validation for PayPal (should fail)
    logger.info("\n3. Testing PayPal validation (should fail)...")

    validate_pp_task = Task(
        id="val_pp",
        name="validate_paypal",
        workflow_id="xor_test",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {
                    "expression": "payment_type == 'paypal'",
                    "name": "is_paypal"
                }
            ],
            "on_failure": "skip",
            "context": {
                "payment_type": resolved_payment_type  # Same resolved value
            }
        }
    )

    pp_validation = await validation_handler.execute(validate_pp_task)
    logger.info(f"PayPal validation: valid={pp_validation.result['valid']}")
    assert pp_validation.result['valid'] == False

    # Step 4: Test validation for crypto (should fail)
    logger.info("\n4. Testing crypto validation (should fail)...")

    validate_crypto_task = Task(
        id="val_crypto",
        name="validate_crypto",
        workflow_id="xor_test",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {
                    "expression": "payment_type == 'crypto'",
                    "name": "is_crypto"
                }
            ],
            "on_failure": "skip",
            "context": {
                "payment_type": resolved_payment_type
            }
        }
    )

    crypto_validation = await validation_handler.execute(validate_crypto_task)
    logger.info(f"Crypto validation: valid={crypto_validation.result['valid']}")
    assert crypto_validation.result['valid'] == False

    # Step 5: Verify XOR property - exactly one validation passed
    logger.info("\n5. Verifying XOR property...")
    validations = [
        cc_validation.result['valid'],
        pp_validation.result['valid'],
        crypto_validation.result['valid']
    ]

    passed_count = sum(1 for v in validations if v)
    logger.info(f"Validations passed: {passed_count} out of 3")
    logger.info(f"XOR satisfied: {passed_count == 1}")
    assert passed_count == 1, "Exactly one validation should pass"

    # Step 6: Test with multiple values in context
    logger.info("\n6. Testing with multiple context values...")

    complex_task = Task(
        id="val_complex",
        name="validate_complex",
        workflow_id="xor_test",
        protocol="validation/v1",
        method="validation/evaluate",
        params={
            "conditions": [
                {
                    "expression": "payment_type == 'credit_card' and amount > 50",
                    "name": "credit_and_amount"
                }
            ],
            "context": {
                "payment_type": resolved_payment_type,
                "amount": payment_data['amount']
            }
        }
    )

    complex_validation = await validation_handler.execute(complex_task)
    logger.info(f"Complex validation: valid={complex_validation.result['valid']}")
    assert complex_validation.result['valid'] == True

    logger.info("\n✅ XOR validation test passed!")


async def test_gate_xor():
    """Test XOR using gate method"""
    logger.info("\n\nTesting XOR with gate method...")

    validation_handler = ValidationHandler()

    # Test gate that enables exactly one path
    gate_task = Task(
        id="gate_1",
        name="route_gate",
        workflow_id="xor_test",
        protocol="validation/v1",
        method="validation/gate",
        params={
            "rules": [
                {
                    "name": "credit_route",
                    "condition": "payment_type == 'credit_card'",
                    "enable_tasks": ["process_credit"],
                    "disable_tasks": ["process_paypal", "process_crypto"]
                },
                {
                    "name": "paypal_route",
                    "condition": "payment_type == 'paypal'",
                    "enable_tasks": ["process_paypal"],
                    "disable_tasks": ["process_credit", "process_crypto"]
                },
                {
                    "name": "crypto_route",
                    "condition": "payment_type == 'crypto'",
                    "enable_tasks": ["process_crypto"],
                    "disable_tasks": ["process_credit", "process_paypal"]
                }
            ],
            "context": {
                "payment_type": "credit_card"
            }
        }
    )

    gate_result = await validation_handler.execute(gate_task)
    logger.info(f"Gate result: {gate_result.result}")

    control = gate_result.result['control']
    logger.info(f"Enabled tasks: {control['enable_tasks']}")
    logger.info(f"Disabled/skipped tasks: {control['skip_tasks']}")

    # Verify XOR - exactly one task enabled
    assert len(control['enable_tasks']) == 1
    assert 'process_credit' in control['enable_tasks']
    assert set(control['skip_tasks']) == {'process_paypal', 'process_crypto'}

    logger.info("✅ Gate XOR test passed!")


async def test_dynamic_xor():
    """Test XOR with dynamically generated conditions"""
    logger.info("\n\nTesting dynamic XOR...")

    python_handler = PythonHandler()
    validation_handler = ValidationHandler()

    # Generate random priority
    priority_task = Task(
        id="prio_1",
        name="get_priority",
        workflow_id="xor_test",
        protocol="python/v1",
        method="python/execute",
        params={
            "code": """
import random
priority = random.randint(1, 10)
result = {'priority': priority}
print(f"Generated priority: {priority}")
"""
        }
    )

    prio_result = await python_handler.execute(priority_task)
    priority_value = prio_result.result['priority']
    logger.info(f"Priority value: {priority_value}")

    # Create XOR validations for priority ranges
    validations = []
    ranges = [
        ("low", "priority <= 3"),
        ("medium", "priority > 3 and priority <= 7"),
        ("high", "priority > 7")
    ]

    for name, expression in ranges:
        val_task = Task(
            id=f"val_{name}",
            name=f"validate_{name}",
            workflow_id="xor_test",
            protocol="validation/v1",
            method="validation/evaluate",
            params={
                "conditions": [
                    {
                        "expression": expression,
                        "name": f"{name}_priority"
                    }
                ],
                "context": {
                    "priority": priority_value
                }
            }
        )

        result = await validation_handler.execute(val_task)
        validations.append((name, result.result['valid']))
        logger.info(f"{name.capitalize()} priority validation: {result.result['valid']}")

    # Verify exactly one validation passed
    passed = [name for name, valid in validations if valid]
    logger.info(f"Passed validations: {passed}")
    assert len(passed) == 1, f"Expected exactly 1 validation to pass, got {len(passed)}"

    logger.info("✅ Dynamic XOR test passed!")


async def main():
    """Run all XOR tests"""
    try:
        await test_xor_with_context()
        await test_gate_xor()
        await test_dynamic_xor()
        logger.info("\n🎉 All XOR validation tests passed successfully!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())