#!/usr/bin/env python3

"""
Demo: CLI Usage for Mixed Vision + Text Workflow

Shows the exact commands and expected output for using vision workflows via CLI.
"""

import subprocess
import time
import asyncio
import os

def print_header(title):
    print(f"\n{'='*60}")
    print(f"🎯 {title}")
    print(f"{'='*60}")

def print_command(cmd):
    print(f"\n💻 Command: {cmd}")
    print("-" * 40)

async def demo_cli_usage():
    print_header("CLI Usage Demo for Mixed Vision + Text Workflow")
    
    print("""
📋 Available Workflows:
   - examples/mixed_vision_text_workflow.yaml (2 tasks: vision + text)
   - examples/vision_workflow.yaml (3 tasks: vision + 2x text)
""")
    
    print_header("Prerequisites Check")
    
    print_command("ollama list")
    try:
        result = subprocess.run(['ollama', 'list'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ Ollama is available")
            if 'llava' in result.stdout:
                print("✅ LLaVa model found")
            else:
                print("⚠️  LLaVa not found. Run: ollama pull llava:latest")
        else:
            print("❌ Ollama not available")
    except Exception as e:
        print(f"❌ Error checking Ollama: {e}")
    
    print_header("CLI Usage Examples")
    
    examples = [
        {
            "title": "Option 1: One-Command Execution",
            "commands": [
                "gleitzeit run examples/mixed_vision_text_workflow.yaml"
            ],
            "description": "Starts everything and runs the workflow in one command"
        },
        {
            "title": "Option 2: Step-by-Step",
            "commands": [
                "gleitzeit start",
                "gleitzeit submit examples/mixed_vision_text_workflow.yaml",
                "gleitzeit status"
            ],
            "description": "Manual control over each step"
        },
        {
            "title": "Option 3: Background Mode",
            "commands": [
                "gleitzeit start --background",
                "gleitzeit submit examples/mixed_vision_text_workflow.yaml",
                "gleitzeit monitor"
            ],
            "description": "Non-blocking startup with real-time monitoring"
        }
    ]
    
    for example in examples:
        print(f"\n🔹 {example['title']}")
        print(f"   {example['description']}")
        print()
        for cmd in example['commands']:
            print(f"   $ {cmd}")
    
    print_header("Expected Workflow Output")
    
    print("""
When you run the mixed workflow, you'll see output like:

🧪 Running workflow: examples/mixed_vision_text_workflow.yaml
ℹ️  Hub not detected, starting automatically on 127.0.0.1:8001
✅ Hub started in background on http://127.0.0.1:8001
ℹ️  Starting Queue Manager...
ℹ️  Starting Dependency Resolver...
ℹ️  Starting Execution Engine...
✅ Started components: Queue Manager, Dependency Resolver, Execution Engine
ℹ️  Submitted task: analyze-scene
ℹ️  Submitted task: write-story
✅ Workflow submitted successfully!

📊 Task analyze-scene: The image is a colorful pattern with red, blue, green, yellow sections...
📊 Task write-story: As Luna's fingers danced across the ancient loom, the colorful threads...

✅ Workflow completed successfully!
""")
    
    print_header("Status and Monitoring Commands")
    
    monitoring_commands = [
        ("gleitzeit status", "Show current hub and component status"),
        ("gleitzeit monitor", "Real-time monitoring of workflow execution"),
        ("gleitzeit providers", "List available providers (including vision)"),
        ("gleitzeit submit --help", "Show all submission options")
    ]
    
    for cmd, desc in monitoring_commands:
        print(f"💻 {cmd}")
        print(f"   {desc}")
        print()
    
    print_header("Custom Vision Workflow")
    
    print("""
To create your own vision workflow:

1. Create a YAML file:
   
   name: "My Vision Task"
   tasks:
     - id: analyze
       method: llm/vision
       parameters:
         model: llava:latest
         prompt: "What do you see?"
         images: ["<your-base64-image>"]
     
     - id: respond
       method: llm/chat
       dependencies: ["analyze"]
       parameters:
         model: llama3.2
         messages:
           - role: user
             content: "Based on: ${analyze.response}, tell me more."

2. Submit it:
   $ gleitzeit submit my_vision_workflow.yaml
""")
    
    print_header("Troubleshooting")
    
    troubleshooting = [
        ("No providers available", "Start vision provider: python test_vision_extension.py"),
        ("LLaVa model not found", "Install model: ollama pull llava:latest"),
        ("Hub connection failed", "Start hub: gleitzeit start --hub-only"),
        ("Workflow timeout", "Increase timeout in YAML or use --wait flag"),
    ]
    
    for issue, solution in troubleshooting:
        print(f"❌ {issue}")
        print(f"✅ {solution}")
        print()
    
    print_header("Ready to Use!")
    
    print("""
🎉 The mixed vision + text workflow is ready for CLI usage!

Quick test:
$ gleitzeit run examples/mixed_vision_text_workflow.yaml

This will:
1. Analyze the test image with LLaVa
2. Generate a creative story with Ollama based on the visual description
3. Return both results through the CLI
""")

if __name__ == "__main__":
    asyncio.run(demo_cli_usage())