#!/usr/bin/env python3
"""
Test file input workflow with file handler and Ollama integration.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from gleitzeit.core.models import Workflow, Task
from gleitzeit.handlers.ollama import OllamaHandler
from gleitzeit.handlers.file import FileHandler

async def test_file_handler_directly():
    """Test the file handler directly"""

    print("=" * 60)
    print("Direct File Handler Test")
    print("=" * 60)

    file_handler = FileHandler()

    # Test loading text file
    text_task = Task(
        id="load_text",
        workflow_id="test",
        name="Load Text File",
        protocol="file/v1",
        method="file/load",
        params={
            "path": "input_file.txt",
            "encoding": "utf-8"
        }
    )

    print("📄 Loading text file...")
    result = await file_handler.execute(text_task)

    if result.status == 'completed':
        print(f"✓ Text file loaded successfully")
        print(f"  Size: {result.result['metadata']['size']} bytes")
        print(f"  Content preview: {result.result['content'][:100]}...")
    else:
        print(f"✗ Failed: {result.error}")

    # Test loading image file
    image_task = Task(
        id="load_image",
        workflow_id="test",
        name="Load Image File",
        protocol="file/v1",
        method="file/load",
        params={
            "path": "sample_image.png",
            "as_base64": True
        }
    )

    print("\n🖼️  Loading image file...")
    result = await file_handler.execute(image_task)

    if result.status == 'completed':
        print(f"✓ Image file loaded successfully")
        print(f"  Size: {result.result['metadata']['size']} bytes")
        print(f"  Encoding: {result.result['metadata']['encoding']}")
        print(f"  Base64 length: {len(result.result['content'])}")
    else:
        print(f"✗ Failed: {result.error}")

    # Test file listing
    list_task = Task(
        id="list_files",
        workflow_id="test",
        name="List Files",
        protocol="file/v1",
        method="file/list",
        params={
            "directory": ".",
            "pattern": "*.txt"
        }
    )

    print("\n📁 Listing files...")
    result = await file_handler.execute(list_task)

    if result.status == 'completed':
        print(f"✓ Found {result.result['count']} files")
        for file_info in result.result['files'][:3]:
            print(f"  - {file_info['name']} ({file_info['size']} bytes)")
    else:
        print(f"✗ Failed: {result.error}")

async def test_file_with_ollama():
    """Test combining file loading with Ollama processing"""

    print("\n" + "=" * 60)
    print("File + Ollama Integration Test")
    print("=" * 60)

    file_handler = FileHandler()
    ollama_handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 120,
        'default_model': 'llama3.2'
    })

    # Step 1: Load the text file
    print("📄 Step 1: Loading text file...")
    text_task = Task(
        id="load_document",
        workflow_id="file_ollama_test",
        name="Load Document",
        protocol="file/v1",
        method="file/load",
        params={"path": "input_file.txt"}
    )

    file_result = await file_handler.execute(text_task)

    if file_result.status != 'completed':
        print(f"✗ Failed to load file: {file_result.error}")
        return

    file_content = file_result.result['content']
    print(f"✓ Loaded file ({len(file_content)} characters)")

    # Step 2: Summarize the content with Ollama
    print("\n🤖 Step 2: Summarizing with Ollama...")
    summary_task = Task(
        id="summarize",
        workflow_id="file_ollama_test",
        name="Summarize Document",
        protocol="ollama/v1",
        method="ollama/generate",
        params={
            "model": "llama3.2",
            "prompt": f"Summarize this document in 2-3 sentences:\n\n{file_content}",
            "options": {
                "temperature": 0.3,
                "num_predict": 100
            }
        }
    )

    summary_result = await ollama_handler.execute(summary_task)

    if summary_result.status == 'completed':
        summary = summary_result.result.get('response', '')
        print(f"✓ Summary generated:")
        print(f"  {summary}")
    else:
        print(f"✗ Summary failed: {summary_result.error}")
        return

    # Step 3: Load and analyze image if available
    image_path = Path("sample_image.png")
    if image_path.exists():
        print("\n🖼️  Step 3: Loading and analyzing image...")

        # Load image as base64
        image_task = Task(
            id="load_image",
            workflow_id="file_ollama_test",
            name="Load Image",
            protocol="file/v1",
            method="file/load",
            params={
                "path": "sample_image.png",
                "as_base64": True
            }
        )

        image_result = await file_handler.execute(image_task)

        if image_result.status == 'completed':
            image_b64 = image_result.result['content']
            print(f"✓ Image loaded (base64 length: {len(image_b64)})")

            # Analyze image with llava
            vision_task = Task(
                id="analyze_image",
                workflow_id="file_ollama_test",
                name="Analyze Image",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llava",
                    "prompt": "Describe what you see in this image in detail.",
                    "images": [image_b64],
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 150
                    }
                }
            )

            vision_result = await ollama_handler.execute(vision_task)

            if vision_result.status == 'completed':
                description = vision_result.result.get('response', '')
                print(f"✓ Image analysis:")
                print(f"  {description}")

                # Create final report
                print("\n📊 Step 4: Creating final report...")
                report_task = Task(
                    id="create_report",
                    workflow_id="file_ollama_test",
                    name="Create Report",
                    protocol="ollama/v1",
                    method="ollama/chat",
                    params={
                        "model": "llama3.2",
                        "messages": [
                            {"role": "system", "content": "You are a helpful assistant that creates comprehensive reports."},
                            {"role": "user", "content": f"Create a brief report combining the following analysis:\n\nDocument Summary: {summary}\n\nImage Description: {description}"}
                        ],
                        "options": {
                            "temperature": 0.5,
                            "num_predict": 200
                        }
                    }
                )

                report_result = await ollama_handler.execute(report_task)

                if report_result.status == 'completed':
                    report = report_result.result.get('message', {}).get('content', '')
                    print(f"✓ Final report:")
                    print(f"  {report}")
                else:
                    print(f"✗ Report failed: {report_result.error}")
            else:
                print(f"✗ Image analysis failed: {vision_result.error}")
        else:
            print(f"✗ Image loading failed: {image_result.error}")

async def test_multiple_files():
    """Test loading multiple files at once"""

    print("\n" + "=" * 60)
    print("Multiple Files Test")
    print("=" * 60)

    file_handler = FileHandler()

    # Create additional test files
    test_files = {
        "test1.txt": "This is test file 1 with some sample content.",
        "test2.txt": "This is test file 2 with different content.",
        "test3.txt": "This is test file 3 with more sample text."
    }

    for filename, content in test_files.items():
        Path(filename).write_text(content)

    # Load multiple files
    multi_task = Task(
        id="load_multiple",
        workflow_id="multi_test",
        name="Load Multiple Files",
        protocol="file/v1",
        method="file/load_multiple",
        params={
            "paths": list(test_files.keys())
        }
    )

    print("📄 Loading multiple files...")
    result = await file_handler.execute(multi_task)

    if result.status == 'completed':
        print(f"✓ Loaded {result.result['loaded']}/{result.result['total']} files")

        for file_data in result.result['files']:
            if file_data['status'] == 'loaded':
                print(f"  ✓ {file_data['path']}: {len(file_data['content'])} chars")
            else:
                print(f"  ✗ {file_data['path']}: {file_data['error']}")
    else:
        print(f"✗ Failed: {result.error}")

    # Clean up test files
    for filename in test_files.keys():
        Path(filename).unlink(missing_ok=True)

async def main():
    """Main test runner"""

    print("File Input Workflow Test")
    print("=" * 60)

    # Test file handler directly
    await test_file_handler_directly()

    # Test file + Ollama integration
    await test_file_with_ollama()

    # Test multiple files
    await test_multiple_files()

    print("\n" + "=" * 60)
    print("All Tests Complete")
    print("=" * 60)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTests interrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()