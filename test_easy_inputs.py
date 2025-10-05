#!/usr/bin/env python3
"""
Test Easy Client with proper result chaining using inputs parameter.
The 'inputs' parameter is resolved by Gleitzeit and made available to tasks.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t, w


def test_simple_chain_with_inputs():
    """Test simple result chaining using inputs"""
    print("\n" + "="*60)
    print("TEST 1: Simple Result Chaining with Inputs")
    print("="*60)

    print("\n1. Creating workflow with result chaining...")

    # Create tasks with references
    generate = t("generate", "python/v1:execute").with_(code="""
# Generate some data
result = {
    'number': 42,
    'message': 'Hello from generate task'
}
print(f'Generated: {result}')
""")

    process = t("process", "python/v1:execute").input(generate).with_(code="""
# 'generate' variable is automatically available
print(f'Received from generate task: {generate}')

result = {
    'doubled': generate.get('number', 0) * 2,
    'response': f\"Processed: {generate.get('message', 'none')}\"
}
print(f'Processed result: {result}')
""")

    workflow = w(generate).sequential(process).name("simple_chain_with_inputs")

    print("   ✅ Workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_ollama_with_inputs():
    """Test passing Python results to Ollama"""
    print("\n" + "="*60)
    print("TEST 2: Python -> Ollama with Inputs")
    print("="*60)

    print("\n1. Creating workflow...")

    # Create tasks with references
    prepare = t("prepare", "python/v1:execute").with_(code="""
# Prepare data
result = {
    'topic': 'Python programming',
    'question_type': 'benefit'
}
print(f'Prepared: {result}')
""")

    ask_ollama = t("ask_ollama", "ollama/v1:chat").with_(
        model="llama3.2:latest",
        messages=[{
            "role": "user",
            "content": "Name one benefit of ${prepare.result.topic}. One short sentence only."
        }]
    )

    summarize = t("summarize", "python/v1:execute").input(prepare, ask_ollama).with_(code="""
# 'prepare' and 'ask_ollama' variables are automatically available
print(f'Topic was: {prepare}')
print(f'LLM said: {ask_ollama}')

result = {
    'topic': prepare.get('topic', 'unknown'),
    'answer': ask_ollama,
    'summary': f\"Asked about {prepare.get('topic', 'unknown')}, got: {ask_ollama}\"
}
print(f'Summary: {result}')
""")

    workflow = w(prepare).sequential(ask_ollama).sequential(summarize).name("ollama_with_inputs")

    print("   ✅ Workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_fan_out_aggregation_with_inputs():
    """Test fan-out with aggregation using inputs"""
    print("\n" + "="*60)
    print("TEST 3: Fan-Out Aggregation with Inputs")
    print("="*60)

    print("\n1. Creating workflow...")

    # Create tasks with references
    source = t("source", "python/v1:execute").with_(code="""
result = [10, 20, 30]
print(f'Source numbers: {result}')
""")

    square1 = t("square1", "python/v1:execute").input(source).with_(code="""
# 'source' variable is automatically available
num = source[0] if len(source) > 0 else 0
result = num * num
print(f'Squared {num} = {result}')
""")

    square2 = t("square2", "python/v1:execute").input(source).with_(code="""
num = source[1] if len(source) > 1 else 0
result = num * num
print(f'Squared {num} = {result}')
""")

    square3 = t("square3", "python/v1:execute").input(source).with_(code="""
num = source[2] if len(source) > 2 else 0
result = num * num
print(f'Squared {num} = {result}')
""")

    aggregate = t("aggregate", "python/v1:execute").input(square1, square2, square3).with_(code="""
# square1, square2, square3 variables are automatically available
result = {
    'squares': [square1, square2, square3],
    'sum': square1 + square2 + square3
}
print(f'Aggregated: {result}')
""")

    workflow = w(source).fan_out(source, square1, square2, square3).fan_in(square1, square2, square3, aggregator=aggregate).name("fan_out_with_inputs")

    print("   ✅ Workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("EASY CLIENT WITH PROPER RESULT CHAINING")
    print("Testing against: http://localhost:8000")
    print("="*60)

    workflow_ids = []

    # Run tests
    wf1 = test_simple_chain_with_inputs()
    if wf1:
        workflow_ids.append(('simple-chain', wf1))

    time.sleep(2)

    wf2 = test_ollama_with_inputs()
    if wf2:
        workflow_ids.append(('ollama-chain', wf2))

    time.sleep(2)

    wf3 = test_fan_out_aggregation_with_inputs()
    if wf3:
        workflow_ids.append(('fan-out-aggregate', wf3))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"\nSubmitted {len(workflow_ids)} workflows:")
    for name, wf_id in workflow_ids:
        print(f"  - {name}: {wf_id}")

    if workflow_ids:
        print("\n✅ All workflows submitted!")
        print("\nThese workflows demonstrate proper result chaining:")
        print("  - Task results are passed via 'inputs' parameter")
        print("  - Parameter expressions ${task.result} are resolved by Gleitzeit")
        print("  - Works with Python, Ollama, and mixed workflows")
    else:
        print("\n⚠️ No workflows were submitted")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
