#!/usr/bin/env python3
"""
Demonstrate using files as input for Ollama workflows.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from gleitzeit.core.models import Workflow, Task
from gleitzeit.handlers.ollama import OllamaHandler

async def run_file_input_workflow():
    """Run workflow that processes file content with Ollama"""

    print("=" * 60)
    print("File Input Ollama Workflow")
    print("=" * 60)

    # Read the input file
    input_file = Path("input_file.txt")
    if not input_file.exists():
        print(f"Error: {input_file} not found")
        return

    with open(input_file, 'r') as f:
        file_content = f.read()

    print(f"\nLoaded file: {input_file}")
    print(f"File size: {len(file_content)} characters")
    print(f"Preview: {file_content[:100]}...")

    # Create handler
    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 120,
        'default_model': 'llama3.2'
    })

    # Create workflow with tasks that process the file content
    workflow_id = f"file-workflow-{datetime.now().timestamp()}"

    workflow = Workflow(
        id=workflow_id,
        name="File Processing Workflow",
        version="1.0.0",
        description="Process file content with Ollama",
        tasks=[
            Task(
                id="summarize",
                workflow_id=workflow_id,
                name="Summarize File Content",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": f"Summarize this text in 2-3 sentences:\n\n{file_content}",
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 100
                    }
                }
            ),
            Task(
                id="extract_keywords",
                workflow_id=workflow_id,
                name="Extract Keywords",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": f"Extract 5 key terms or concepts from this text. List them as bullet points:\n\n{file_content}",
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 50
                    }
                }
            ),
            Task(
                id="generate_questions",
                workflow_id=workflow_id,
                name="Generate Questions",
                protocol="ollama/v1",
                method="ollama/chat",
                params={
                    "model": "llama3.2",
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that creates thoughtful questions."},
                        {"role": "user", "content": f"Based on this text, generate 3 interesting questions a reader might have:\n\n{file_content}"}
                    ],
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 150
                    }
                },
                dependencies=["summarize"]
            ),
            Task(
                id="sentiment_analysis",
                workflow_id=workflow_id,
                name="Analyze Sentiment",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llama3.2",
                    "prompt": f"Analyze the overall sentiment and tone of this text (positive/negative/neutral, formal/informal, etc.):\n\n{file_content}",
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 50
                    }
                }
            )
        ]
    )

    print(f"\nExecuting {len(workflow.tasks)} tasks on file content...")
    print("=" * 60)

    # Execute tasks
    results = {}
    completed = set()

    while len(completed) < len(workflow.tasks):
        for task in workflow.tasks:
            if task.id in completed:
                continue

            # Check dependencies
            if task.dependencies:
                if not all(dep in completed for dep in task.dependencies):
                    continue

            print(f"\n📄 {task.name}...")

            try:
                result = await handler.execute(task)
                results[task.id] = result
                completed.add(task.id)

                if result.status == 'completed':
                    if task.method == "ollama/generate":
                        response = result.result.get('response', '')
                        print(f"✓ Result: {response[:200]}...")
                    elif task.method == "ollama/chat":
                        message = result.result.get('message', {})
                        content = message.get('content', '')
                        print(f"✓ Result: {content[:200]}...")
                else:
                    print(f"✗ Failed: {result.error}")

            except Exception as e:
                print(f"✗ Error: {e}")
                completed.add(task.id)

    # Display summary
    print("\n" + "=" * 60)
    print("Workflow Results Summary")
    print("=" * 60)

    for task_id, result in results.items():
        task_name = next(t.name for t in workflow.tasks if t.id == task_id)
        if result.status == 'completed':
            if 'response' in result.result:
                output = result.result['response']
            else:
                output = result.result.get('message', {}).get('content', '')

            print(f"\n{task_name}:")
            print("-" * 40)
            print(output)

    return results


async def run_multi_file_workflow():
    """Process multiple files in a workflow"""

    print("\n\n" + "=" * 60)
    print("Multi-File Processing Workflow")
    print("=" * 60)

    # Create additional sample files
    files_data = {
        "tech_news.txt": "AI breakthrough: New language model achieves human-level reasoning...",
        "science_article.txt": "Researchers discover new exoplanet with potential for life...",
        "business_report.txt": "Q4 earnings exceed expectations with 15% growth..."
    }

    # Create sample files
    for filename, content in files_data.items():
        Path(filename).write_text(content)

    print(f"\nProcessing {len(files_data)} files...")

    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 60,
        'default_model': 'llama3.2'
    })

    # Process each file
    for filename, content in files_data.items():
        print(f"\n📁 Processing: {filename}")

        task = Task(
            id=f"categorize_{filename}",
            workflow_id="multi-file",
            name=f"Categorize {filename}",
            protocol="ollama/v1",
            method="ollama/generate",
            params={
                "model": "llama3.2",
                "prompt": f"Categorize this text (technology/science/business/other) and explain why in one sentence:\n\n{content}",
                "options": {
                    "temperature": 0.3,
                    "num_predict": 30
                }
            }
        )

        result = await handler.execute(task)
        if result.status == 'completed':
            print(f"  Category: {result.result.get('response', 'Unknown')}")


async def main():
    """Main entry point"""

    # Run file input workflow
    await run_file_input_workflow()

    # Run multi-file workflow
    await run_multi_file_workflow()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()