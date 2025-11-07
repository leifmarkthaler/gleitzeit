#!/usr/bin/env python3
"""
Test Easy Client with Ollama workflows.
"""

import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.easy import t, w


def test_simple_ollama():
    """Test a simple Ollama chat completion."""
    print("\n" + "="*60)
    print("TEST 1: Simple Ollama Chat")
    print("="*60)

    print("\n1. Creating Ollama workflow...")
    workflow = w(
        t("chat", "ollama/v1:chat")
            .require('model', 'messages')
            .expect_types(model=str, messages=list)
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "What is 2+2? Answer in one short sentence."}
                ]
            )
            .validate()
    ).name("easy_ollama_chat")

    print("   ✅ Workflow created and validated")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_ollama_pipeline():
    """Test sequential Ollama tasks in a pipeline."""
    print("\n" + "="*60)
    print("TEST 2: Ollama Sequential Pipeline")
    print("="*60)

    print("\n1. Creating pipeline workflow...")
    workflow = w(
        t("analyze", "ollama/v1:chat")
            .require('model', 'messages')
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "Name one interesting fact about space. Keep it short."}
                ]
            )
    ).sequential(
        t("summarize", "ollama/v1:chat")
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "Say 'received' in one word."}
                ]
            )
    ).name("easy_ollama_pipeline")

    print("   ✅ Pipeline workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def test_mixed_workflow():
    """Test mixed workflow with Python and Ollama tasks."""
    print("\n" + "="*60)
    print("TEST 3: Mixed Python + Ollama Workflow")
    print("="*60)

    print("\n1. Creating mixed workflow...")
    workflow = w(
        t("prepare", "python/v1:execute")
            .with_(code="print('Preparing data...'); data = 'ready'")
    ).sequential(
        t("llm_process", "ollama/v1:chat")
            .with_(
                model="llama3.2:latest",
                messages=[
                    {"role": "user", "content": "Say hello in one word."}
                ]
            ),
        t("finalize", "python/v1:execute")
            .with_(code="print('Finalizing...'); result = 'done'")
    ).name("easy_mixed_workflow")

    print("   ✅ Mixed workflow created")
    print("\n   Workflow structure:")
    workflow.print_dag()

    print("\n2. Submitting to Gleitzeit...")
    try:
        response = workflow.submit(api_url="http://localhost:8000")
        print(f"   ✅ Workflow submitted!")
        print(f"      Workflow ID: {response.get('workflow_id')}")
        print(f"      Status: {response.get('status')}")
        return response.get('workflow_id')
    except Exception as e:
        print(f"   ❌ Submission failed: {e}")
        return None


def main():
    """Run all Ollama tests."""
    print("\n" + "="*60)
    print("EASY CLIENT + OLLAMA TEST")
    print("Testing against: http://localhost:8000")
    print("="*60)

    workflow_ids = []

    # Run tests
    wf1 = test_simple_ollama()
    if wf1:
        workflow_ids.append(('simple-ollama', wf1))

    time.sleep(2)

    wf2 = test_ollama_pipeline()
    if wf2:
        workflow_ids.append(('ollama-pipeline', wf2))

    time.sleep(2)

    wf3 = test_mixed_workflow()
    if wf3:
        workflow_ids.append(('mixed-workflow', wf3))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"\nSubmitted {len(workflow_ids)} workflows:")
    for name, wf_id in workflow_ids:
        print(f"  - {name}: {wf_id}")

    if workflow_ids:
        print("\n✅ All workflows submitted successfully!")
        print("\nCheck status with: gleitzeit ps")
    else:
        print("\n⚠️ No workflows were submitted")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
