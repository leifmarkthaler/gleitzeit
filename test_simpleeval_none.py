#!/usr/bin/env python
"""
Test how SimpleEval handles None values in expressions.
"""

from simpleeval import SimpleEval

def test_none_behavior():
    """Test SimpleEval's behavior with None values"""
    
    evaluator = SimpleEval()
    
    print("SimpleEval None Behavior Tests")
    print("="*50)
    
    # Test 1: Direct None comparison
    print("\n1. Direct None comparisons:")
    tests = [
        ("x == None", {"x": None}),
        ("x is None", {"x": None}),
        ("x != None", {"x": None}),
        ("x is not None", {"x": None}),
        ("x == None", {"x": 5}),
        ("x is None", {"x": 5}),
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:20} with {str(context):35} = {result}")
        except Exception as e:
            print(f"  {expr:20} with {str(context):35} = ERROR: {e}")
    
    # Test 2: None in logical operations
    print("\n2. None in logical operations:")
    tests = [
        ("x and y", {"x": None, "y": True}),
        ("x or y", {"x": None, "y": True}),
        ("x and y", {"x": True, "y": None}),
        ("x or y", {"x": False, "y": None}),
        ("not x", {"x": None}),
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:20} with {str(context):35} = {result}")
        except Exception as e:
            print(f"  {expr:20} with {str(context):35} = ERROR: {e}")
    
    # Test 3: None in arithmetic operations (should fail)
    print("\n3. None in arithmetic operations:")
    tests = [
        ("x + 1", {"x": None}),
        ("x > 5", {"x": None}),
        ("x < 10", {"x": None}),
        ("x >= 0", {"x": None}),
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:20} with {str(context):35} = {result}")
        except Exception as e:
            error_type = type(e).__name__
            print(f"  {expr:20} with {str(context):35} = {error_type}: {e}")
    
    # Test 4: None with default values
    print("\n4. Using None with default patterns:")
    tests = [
        ("x if x is not None else 0", {"x": None}),
        ("x if x is not None else 0", {"x": 5}),
        ("x or 10", {"x": None}),
        ("x or 10", {"x": 0}),
        ("x or 10", {"x": 5}),
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:30} with {str(context):35} = {result}")
        except Exception as e:
            print(f"  {expr:30} with {str(context):35} = ERROR: {e}")
    
    # Test 5: None in complex conditions
    print("\n5. Complex conditions with None:")
    tests = [
        ("x > 100 if x is not None else False", {"x": None}),
        ("x > 100 if x is not None else False", {"x": 150}),
        ("x > 100 if x is not None else False", {"x": 50}),
        ("(x or 0) > 100", {"x": None}),
        ("(x or 0) > 100", {"x": 150}),
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:40} with {str(context):35} = {result}")
        except Exception as e:
            print(f"  {expr:40} with {str(context):35} = ERROR: {e}")
    
    # Test 6: Missing variables (undefined vs None)
    print("\n6. Undefined vs None:")
    tests = [
        ("x", {}),  # x is undefined
        ("x", {"x": None}),  # x is None
        ("x == None", {}),  # x is undefined
        ("x or 'default'", {}),  # x is undefined
        ("x or 'default'", {"x": None}),  # x is None
    ]
    
    for expr, context in tests:
        try:
            evaluator.names = context
            result = evaluator.eval(expr)
            print(f"  {expr:20} with {str(context):35} = {result}")
        except Exception as e:
            error_type = type(e).__name__
            print(f"  {expr:20} with {str(context):35} = {error_type}")

    # Test 7: Safe patterns for handling None
    print("\n7. Recommended patterns for handling None:")
    print("\nFor validation tasks in Gleitzeit:")
    
    # Simulate workflow context with possible None values
    workflow_context = {
        "order_total": 1500,
        "customer_type": "premium",
        "discount_code": None,
        "shipping_address": None,
    }
    
    validation_rules = [
        ("order_total > 1000", "Check order is large"),
        ("customer_type == 'premium'", "Check premium customer"),
        ("discount_code is not None", "Check discount exists"),
        ("shipping_address is not None", "Check shipping address exists"),
        ("(order_total or 0) > 1000", "Safe order check with default"),
        ("discount_code is None or discount_code == 'VALID'", "Optional discount check"),
    ]
    
    for expr, description in validation_rules:
        try:
            evaluator.names = workflow_context
            result = evaluator.eval(expr)
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"  {status} - {description:35} | {expr:50} = {result}")
        except Exception as e:
            print(f"  ✗ ERROR - {description:35} | {expr:50} = {e}")

if __name__ == "__main__":
    test_none_behavior()