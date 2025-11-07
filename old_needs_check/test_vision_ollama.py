#!/usr/bin/env python3
"""
Demonstrate using images with Ollama vision models (llava).
"""

import asyncio
import base64
import json
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import io

from gleitzeit.core.models import Workflow, Task
from gleitzeit.handlers.ollama import OllamaHandler


def create_sample_image(filename="sample_image.png"):
    """Create a sample image for testing"""
    # Create a simple image with shapes and text
    width, height = 800, 600
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)

    # Draw some shapes
    # Blue rectangle
    draw.rectangle([50, 50, 250, 200], fill='blue', outline='black', width=3)
    draw.text((100, 120), "BLUE BOX", fill='white')

    # Red circle
    draw.ellipse([300, 100, 500, 300], fill='red', outline='black', width=3)
    draw.text((350, 190), "RED CIRCLE", fill='white')

    # Green triangle
    triangle = [(600, 250), (700, 100), (750, 250)]
    draw.polygon(triangle, fill='green', outline='black', width=3)
    draw.text((650, 180), "GREEN", fill='white')

    # Yellow star (simplified)
    star_points = [
        (150, 350), (175, 425), (100, 375),
        (200, 375), (125, 425)
    ]
    draw.polygon(star_points, fill='yellow', outline='black', width=2)

    # Add text at bottom
    draw.text((50, 500), "Sample Vision Test Image", fill='black')
    draw.text((50, 530), f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", fill='gray')

    # Draw a simple chart
    draw.rectangle([550, 350, 750, 550], outline='black', width=2)
    bars = [
        (570, 480, 610, 530, 'orange', '25'),
        (620, 430, 660, 530, 'purple', '50'),
        (670, 380, 710, 530, 'cyan', '75')
    ]
    for x1, y1, x2, y2, color, label in bars:
        draw.rectangle([x1, y1, x2, y2], fill=color)
        draw.text((x1+5, y2+5), label, fill='black')

    draw.text((600, 355), "BAR CHART", fill='black')

    # Save image
    image.save(filename)
    print(f"Created sample image: {filename}")
    return filename


def image_to_base64(image_path):
    """Convert image to base64 string for Ollama API"""
    with open(image_path, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8')


async def run_vision_workflow():
    """Run workflow with vision tasks using llava model"""

    print("=" * 60)
    print("Ollama Vision Workflow (llava)")
    print("=" * 60)

    # Create sample image
    image_file = create_sample_image()
    image_b64 = image_to_base64(image_file)

    print(f"\nImage loaded: {image_file}")
    print(f"Base64 size: {len(image_b64)} characters")

    # Create handler
    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 180,  # Vision models take longer
        'default_model': 'llava'
    })

    workflow_id = f"vision-workflow-{datetime.now().timestamp()}"

    # Create workflow with vision tasks
    workflow = Workflow(
        id=workflow_id,
        name="Vision Analysis Workflow",
        version="1.0.0",
        description="Analyze images with llava vision model",
        tasks=[
            Task(
                id="describe_image",
                workflow_id=workflow_id,
                name="Describe Image",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llava",
                    "prompt": "Describe this image in detail. What shapes, colors, and text do you see?",
                    "images": [image_b64],
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 200
                    }
                }
            ),
            Task(
                id="count_shapes",
                workflow_id=workflow_id,
                name="Count Shapes",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llava",
                    "prompt": "Count and list all the geometric shapes you see in this image. Be specific about colors.",
                    "images": [image_b64],
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 100
                    }
                }
            ),
            Task(
                id="analyze_chart",
                workflow_id=workflow_id,
                name="Analyze Chart",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llava",
                    "prompt": "If there is a chart or graph in this image, describe what it shows including any data values you can see.",
                    "images": [image_b64],
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 150
                    }
                }
            ),
            Task(
                id="creative_story",
                workflow_id=workflow_id,
                name="Create Story",
                protocol="ollama/v1",
                method="ollama/generate",
                params={
                    "model": "llava",
                    "prompt": "Create a short, creative story inspired by the shapes and colors in this image. Be imaginative!",
                    "images": [image_b64],
                    "options": {
                        "temperature": 0.9,
                        "num_predict": 150
                    }
                },
                dependencies=["describe_image"]
            )
        ]
    )

    print(f"\nExecuting {len(workflow.tasks)} vision tasks...")
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

            print(f"\n🖼️  {task.name}...")

            try:
                result = await handler.execute(task)
                results[task.id] = result
                completed.add(task.id)

                if result.status == 'completed':
                    response = result.result.get('response', '')
                    print(f"✓ Response: {response[:250]}...")
                    print(f"  (Duration: {result.duration_seconds:.1f}s)")
                else:
                    print(f"✗ Failed: {result.error}")

            except Exception as e:
                print(f"✗ Error: {e}")
                completed.add(task.id)

    # Display full results
    print("\n" + "=" * 60)
    print("Vision Analysis Results")
    print("=" * 60)

    for task_id, result in results.items():
        task_name = next(t.name for t in workflow.tasks if t.id == task_id)
        if result.status == 'completed':
            output = result.result.get('response', 'No response')
            print(f"\n{task_name}:")
            print("-" * 40)
            print(output)

    return results


async def run_multi_image_comparison():
    """Compare multiple images using vision model"""

    print("\n\n" + "=" * 60)
    print("Multi-Image Comparison Workflow")
    print("=" * 60)

    # Create two different images
    image1 = create_sample_image("image1.png")

    # Create a second, different image
    image2_path = "image2.png"
    image2 = Image.new('RGB', (800, 600), 'lightgray')
    draw = ImageDraw.Draw(image2)

    # Different content
    draw.rectangle([100, 100, 300, 300], fill='orange', outline='black', width=3)
    draw.ellipse([400, 150, 600, 350], fill='purple', outline='black', width=3)
    draw.text((200, 400), "Different Image", fill='black')

    image2.save(image2_path)
    print(f"Created second image: {image2_path}")

    # Convert both to base64
    image1_b64 = image_to_base64(image1)
    image2_b64 = image_to_base64(image2_path)

    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 180,
        'default_model': 'llava'
    })

    # Compare images task
    comparison_task = Task(
        id="compare_images",
        workflow_id="comparison",
        name="Compare Two Images",
        protocol="ollama/v1",
        method="ollama/generate",
        params={
            "model": "llava",
            "prompt": "I'm showing you two images. Compare them and describe the main differences you see between the first and second image.",
            "images": [image1_b64, image2_b64],
            "options": {
                "temperature": 0.3,
                "num_predict": 200
            }
        }
    )

    print("\n🔍 Comparing two images...")
    result = await handler.execute(comparison_task)

    if result.status == 'completed':
        print(f"✓ Comparison result:")
        print("-" * 40)
        print(result.result.get('response', 'No response'))
    else:
        print(f"✗ Failed: {result.error}")


async def run_real_world_example():
    """Example with a real-world use case - analyzing screenshots or diagrams"""

    print("\n\n" + "=" * 60)
    print("Real-World Vision Example: UI Analysis")
    print("=" * 60)

    # Create a mock UI screenshot
    ui_image_path = "mock_ui.png"
    image = Image.new('RGB', (1200, 800), 'white')
    draw = ImageDraw.Draw(image)

    # Mock navigation bar
    draw.rectangle([0, 0, 1200, 60], fill='#2c3e50')
    draw.text((50, 20), "MyApp Dashboard", fill='white')
    draw.text((1000, 20), "User: John Doe", fill='white')

    # Mock sidebar
    draw.rectangle([0, 60, 250, 800], fill='#34495e')
    menu_items = ["Dashboard", "Analytics", "Reports", "Settings", "Help"]
    for i, item in enumerate(menu_items):
        y = 100 + i * 50
        draw.rectangle([20, y, 230, y + 35], fill='#2c3e50' if i == 0 else '#34495e')
        draw.text((30, y + 10), item, fill='white')

    # Mock main content area with cards
    cards = [
        (300, 100, 550, 250, '#3498db', 'Total Users', '1,234'),
        (600, 100, 850, 250, '#2ecc71', 'Revenue', '$45,678'),
        (900, 100, 1150, 250, '#e74c3c', 'Issues', '23'),
        (300, 300, 850, 550, '#95a5a6', 'Recent Activity', '[Chart Area]'),
        (900, 300, 1150, 550, '#f39c12', 'Quick Actions', '[Buttons]')
    ]

    for x1, y1, x2, y2, color, title, value in cards:
        draw.rectangle([x1, y1, x2, y2], fill=color)
        draw.text((x1 + 20, y1 + 20), title, fill='white')
        draw.text((x1 + 20, y1 + 80), value, fill='white')

    image.save(ui_image_path)
    print(f"Created mock UI: {ui_image_path}")

    ui_b64 = image_to_base64(ui_image_path)

    handler = OllamaHandler({
        'base_url': 'http://localhost:11434',
        'timeout': 180,
        'default_model': 'llava'
    })

    # Analyze UI
    tasks = [
        Task(
            id="analyze_ui",
            workflow_id="ui-analysis",
            name="Analyze UI Layout",
            protocol="ollama/v1",
            method="ollama/generate",
            params={
                "model": "llava",
                "prompt": "Analyze this user interface. Describe the layout, components, and what type of application this appears to be.",
                "images": [ui_b64],
                "options": {"temperature": 0.3, "num_predict": 200}
            }
        ),
        Task(
            id="suggest_improvements",
            workflow_id="ui-analysis",
            name="Suggest UI Improvements",
            protocol="ollama/v1",
            method="ollama/generate",
            params={
                "model": "llava",
                "prompt": "Based on this UI design, suggest 3 improvements for better user experience.",
                "images": [ui_b64],
                "options": {"temperature": 0.7, "num_predict": 150}
            }
        )
    ]

    for task in tasks:
        print(f"\n💻 {task.name}...")
        result = await handler.execute(task)

        if result.status == 'completed':
            print(f"✓ Analysis:")
            print("-" * 40)
            print(result.result.get('response', 'No response'))
        else:
            print(f"✗ Failed: {result.error}")


async def main():
    """Main entry point"""

    try:
        # Check if PIL is installed
        from PIL import Image
    except ImportError:
        print("Installing Pillow for image creation...")
        import subprocess
        subprocess.check_call(['pip', 'install', 'Pillow'])
        from PIL import Image, ImageDraw

    # Run vision workflows
    await run_vision_workflow()
    await run_multi_image_comparison()
    await run_real_world_example()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nWorkflow interrupted")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()