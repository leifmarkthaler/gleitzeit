#!/usr/bin/env python3
"""
Test Easy Client with result chaining between dependent tasks.
Demonstrates how outputs from one task can be used as inputs to another.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t, w


def test_simple_result_chain():
    """Test simple result chaining: Task A -> Task B"""
    print("\n" + "="*60)
    print("TEST 1: Simple Result Chaining")
    print("="*60)

    print("\n1. Creating workflow with result chaining...")
    workflow = w(
        t("generate", "python/v1:execute")
            .with_(code="""
# Generate some data
result = {
    'number': 42,
    'message': 'Hello from task A'
}
print(f'Generated: {result}')
""")
    ).sequential(
        t("process", "python/v1:execute")
            .with_(code="""
# Access result from previous task using ${generate.result}
import json
prev_result = ${generate.result}
print(f'Received from generate: {prev_result}')

# Process the data
result = {
    'doubled': prev_result['number'] * 2,
    'response': f\"Processed: {prev_result['message']}\"
}
print(f'Processed result: {result}')
""")
    ).name("simple_chain")

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


def test_ollama_with_data():
    """Test passing data to Ollama and processing its response"""
    print("\n" + "="*60)
    print("TEST 2: Python -> Ollama -> Python Chain")
    print("="*60)

    print("\n1. Creating data processing pipeline...")
    workflow = w(
        t("prepare_data", "python/v1:execute")
            .with_(code="""
# Prepare a question for the LLM
result = {
    'question': 'What is 7 * 8? Give just the number.',
    'context': 'math_problem'
}
print(f'Prepared: {result}')
""")
    ).sequential(
        t("ask_llm", "ollama/v1:chat")
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "${prepare_data.result.question}"}
                ]
            )
    ).sequential(
        t("process_answer", "python/v1:execute")
            .with_(code="""
# Process LLM response
llm_response = ${ask_llm.result}
question = ${prepare_data.result.question}

print(f'Question was: {question}')
print(f'LLM answered: {llm_response}')

result = {
    'original_question': question,
    'llm_answer': llm_response,
    'processed': True
}
print(f'Final result: {result}')
""")
    ).name("ollama_chain")

    print("   ✅ Pipeline created")
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


def test_fan_out_with_aggregation():
    """Test fan-out with multiple tasks using the same data, then aggregating"""
    print("\n" + "="*60)
    print("TEST 3: Fan-Out with Result Aggregation")
    print("="*60)

    print("\n1. Creating fan-out aggregation workflow...")
    workflow = w(
        t("source", "python/v1:execute")
            .with_(code="""
# Generate numbers to process
result = {
    'numbers': [10, 20, 30],
    'operation': 'square'
}
print(f'Source data: {result}')
""")
    ).fan_out("source",
        t("square_first", "python/v1:execute")
            .with_(code="""
data = ${source.result}
num = data['numbers'][0]
result = num * num
print(f'Squared {num} = {result}')
"""),
        t("square_second", "python/v1:execute")
            .with_(code="""
data = ${source.result}
num = data['numbers'][1]
result = num * num
print(f'Squared {num} = {result}')
"""),
        t("square_third", "python/v1:execute")
            .with_(code="""
data = ${source.result}
num = data['numbers'][2]
result = num * num
print(f'Squared {num} = {result}')
""")
    ).fan_in("square_first", "square_second", "square_third",
        aggregator=t("aggregate", "python/v1:execute")
            .with_(code="""
# Aggregate all results
r1 = ${square_first.result}
r2 = ${square_second.result}
r3 = ${square_third.result}

result = {
    'squares': [r1, r2, r3],
    'sum': r1 + r2 + r3
}
print(f'Aggregated results: {result}')
""")
    ).name("fan_out_aggregation")

    print("   ✅ Fan-out aggregation workflow created")
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


def test_multi_llm_chain():
    """Test chaining multiple LLM calls"""
    print("\n" + "="*60)
    print("TEST 4: Multi-LLM Chain with Context")
    print("="*60)

    print("\n1. Creating multi-LLM conversation...")
    workflow = w(
        t("ask_question", "ollama/v1:chat")
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "Name a color. Just one word."}
                ]
            )
    ).sequential(
        t("ask_followup", "ollama/v1:chat")
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "I got the color: ${ask_question.result}. Now name a fruit of that color. One word only."}
                ]
            )
    ).sequential(
        t("summarize", "python/v1:execute")
            .with_(code="""
color = ${ask_question.result}
fruit = ${ask_followup.result}

result = f'Color: {color}, Fruit: {fruit}'
print(f'Summary: {result}')
""")
    ).name("multi_llm_chain")

    print("   ✅ Multi-LLM chain created")
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
    """Run all result chaining tests."""
    print("\n" + "="*60)
    print("EASY CLIENT RESULT CHAINING TEST")
    print("Testing against: http://localhost:8000")
    print("="*60)

    workflow_ids = []

    # Run tests
    wf1 = test_simple_result_chain()
    if wf1:
        workflow_ids.append(('simple-chain', wf1))

    time.sleep(2)

    wf2 = test_ollama_with_data()
    if wf2:
        workflow_ids.append(('ollama-chain', wf2))

    time.sleep(2)

    wf3 = test_fan_out_with_aggregation()
    if wf3:
        workflow_ids.append(('fan-out-aggregate', wf3))

    time.sleep(2)

    wf4 = test_multi_llm_chain()
    if wf4:
        workflow_ids.append(('multi-llm', wf4))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"\nSubmitted {len(workflow_ids)} workflows:")
    for name, wf_id in workflow_ids:
        print(f"  - {name}: {wf_id}")

    if workflow_ids:
        print("\n✅ All result chaining workflows submitted!")
        print("\nCheck status with: gleitzeit ps")
    else:
        print("\n⚠️ No workflows were submitted")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
