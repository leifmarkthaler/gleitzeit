#!/usr/bin/env python
"""
Test SimpleEval edge cases: no conditions met and None inputs
"""

from simpleeval import SimpleEval

def test_edge_cases():
    """Test SimpleEval with edge cases for validation tasks"""

    evaluator = SimpleEval()

    print("SimpleEval Edge Cases for Validation Tasks")
    print("="*50)

    # Test 1: Empty conditions / No conditions to evaluate
    print("\n1. Empty/No Conditions:")
    tests = [
        ("True", {}),  # Always true - fallback
        ("False", {}),  # Always false - fallback
        ("None", {}),  # Evaluates to None
        ("", {}),  # Empty string (should fail)
    ]

    for expr, context in tests:
        try:
            evaluator.names = context
            if expr == "":
                print(f"  Empty expression: Cannot evaluate")
                continue
            result = evaluator.eval(expr)
            print(f"  {expr:20} = {result} (type: {type(result).__name__}, truthy: {bool(result)})")
        except Exception as e:
            print(f"  {expr:20} = ERROR: {e}")

    # Test 2: All conditions evaluate to False/None
    print("\n2. All Conditions False or None:")
    conditions = [
        "x > 100",
        "y == 'active'",
        "z is not None"
    ]
    context = {"x": 50, "y": "inactive", "z": None}

    print(f"  Context: {context}")
    results = []
    for cond in conditions:
        evaluator.names = context
        result = evaluator.eval(cond)
        results.append(result)
        print(f"    {cond:20} = {result}")

    print(f"  all(results) = {all(results)}")
    print(f"  any(results) = {any(results)}")
    print(f"  none met = {not any(results)}")

    # Test 3: Input is None (entire input/context is None)
    print("\n3. Input is None:")
    tests = [
        ("input", {"input": None}),
        ("input or 'default'", {"input": None}),
        ("input is None", {"input": None}),
        ("input if input is not None else 'empty'", {"input": None}),
        ("process(input) if input else 'skip'", {"input": None}),
    ]

    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:45} = {result}")
        except Exception as e:
            print(f"  {expr:45} = ERROR: {e}")

    # Test 4: Multiple None values in context
    print("\n4. Multiple None Values:")
    context = {
        "a": None,
        "b": None,
        "c": None,
        "d": 100  # One non-None value
    }

    tests = [
        "a or b or c or d",  # Should return 100
        "a and b and c and d",  # Should return None
        "(a or 0) + (b or 0) + (c or 0) + (d or 0)",  # Should return 100
        "any([a, b, c, d])",  # Would need custom function
        "d if (a is None and b is None and c is None) else 0",
    ]

    print(f"  Context: {context}")
    for expr in tests:
        try:
            evaluator.names = context
            # Add any() function for testing
            if "any(" in expr:
                evaluator.functions["any"] = any
            result = evaluator.eval(expr)
            print(f"    {expr:50} = {result}")
        except Exception as e:
            print(f"    {expr:50} = ERROR: {e}")

    # Test 5: Validation workflow with no conditions met
    print("\n5. Validation Workflow - No Conditions Met:")

    # Simulate a validation task where nothing passes
    workflow_context = {
        "order_total": 500,  # Below threshold
        "customer_type": "basic",  # Not premium
        "discount_code": None,  # No discount
        "payment_method": None,  # No payment method
        "shipping_address": None,  # No address
    }

    validations = [
        ("order_total > 1000", "Large order"),
        ("customer_type == 'premium'", "Premium customer"),
        ("discount_code is not None", "Has discount"),
        ("payment_method is not None", "Payment selected"),
        ("shipping_address is not None", "Address provided"),
    ]

    print(f"  Context: {workflow_context}")
    print("  Validations:")

    passed = []
    failed = []

    for expr, description in validations:
        evaluator.names = workflow_context
        result = evaluator.eval(expr)
        status = "✓" if result else "✗"
        print(f"    {status} {description:25} | {expr:40} = {result}")

        if result:
            passed.append(description)
        else:
            failed.append(description)

    print(f"\n  Summary:")
    print(f"    Passed: {len(passed)} - {passed if passed else 'None'}")
    print(f"    Failed: {len(failed)} - {failed[:3]}..." if len(failed) > 3 else f"    Failed: {len(failed)} - {failed}")
    print(f"    All passed: {len(passed) == len(validations)}")
    print(f"    Any passed: {len(passed) > 0}")
    print(f"    None passed: {len(passed) == 0}")

    # Test 6: Fallback behaviors when no conditions met
    print("\n6. Fallback Strategies When No Conditions Met:")

    # Different strategies for handling "no conditions met"
    strategies = [
        # Strategy 1: Default value
        ("conditions_met or 'use_default'", {"conditions_met": False}),

        # Strategy 2: Explicit check
        ("'proceed' if conditions_met else 'stop'", {"conditions_met": False}),

        # Strategy 3: None as signal
        ("result if result is not None else 'no_result'", {"result": None}),

        # Strategy 4: Empty list check
        ("results[0] if results else 'empty'", {"results": []}),

        # Strategy 5: Count-based
        ("'valid' if valid_count > 0 else 'invalid'", {"valid_count": 0}),
    ]

    for expr, context in strategies:
        evaluator.names = context
        result = evaluator.eval(expr)
        print(f"  {expr:50} = {result}")

    # Test 7: Validation with all None inputs
    print("\n7. Validation with All Inputs None:")

    all_none_context = {
        "input1": None,
        "input2": None,
        "input3": None,
    }

    # How to handle when all inputs are None
    none_handling = [
        ("input1 or input2 or input3 or 'all_none'", "Fallback to default"),
        ("'process' if any([input1, input2, input3]) else 'skip'", "Skip if all None"),
        ("(input1 or 0) + (input2 or 0) + (input3 or 0)", "Treat None as 0"),
        ("input1 is None and input2 is None and input3 is None", "Detect all None"),
    ]

    print(f"  Context: {all_none_context}")
    for expr, description in none_handling:
        try:
            evaluator.names = all_none_context
            if "any(" in expr:
                evaluator.functions["any"] = any
            result = evaluator.eval(expr)
            print(f"  {description:20} | {expr:55} = {result}")
        except Exception as e:
            print(f"  {description:20} | {expr:55} = ERROR: {e}")

if __name__ == "__main__":
    test_edge_cases()