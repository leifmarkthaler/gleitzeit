"""
Gleitzeit V2 CLI

Clean command-line interface using the new architecture.
"""

import asyncio
import argparse
import logging
from typing import Dict, Any

from .client.gleitzeit_client import GleitzeitClient
from .core.models import Task, Workflow, TaskType, TaskParameters, Priority


async def run_text_command(args):
    """Handle text generation command"""
    client = GleitzeitClient(args.server)
    
    try:
        print(f"💬 Generating text with {args.model}...")
        
        result = await client.run_text_generation(
            prompt=args.text,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout
        )
        
        print(f"\n📝 Generated text:")
        print(result)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


async def run_vision_command(args):
    """Handle vision analysis command"""
    client = GleitzeitClient(args.server)
    
    try:
        print(f"👁️ Analyzing image with {args.model}...")
        
        result = await client.run_vision_analysis(
            image_path=args.image,
            prompt=args.prompt or "Describe what you see in this image",
            model=args.model,
            timeout=args.timeout
        )
        
        print(f"\n👁️ Vision analysis:")
        print(result)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


async def run_function_command(args):
    """Handle function execution command"""
    client = GleitzeitClient(args.server)
    
    try:
        # Parse function arguments
        kwargs = {}
        if args.args:
            for arg in args.args:
                if '=' in arg:
                    key, value = arg.split('=', 1)
                    # Try to parse as JSON, fallback to string
                    try:
                        import json
                        kwargs[key] = json.loads(value)
                    except:
                        kwargs[key] = value
        
        print(f"⚡ Running function: {args.function}")
        
        result = await client.run_function(
            function_name=args.function,
            kwargs=kwargs,
            timeout=args.timeout
        )
        
        print(f"\n📊 Result:")
        print(result)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


async def run_workflow_command(args):
    """Handle workflow execution command"""
    client = GleitzeitClient(args.server)
    
    try:
        # Load workflow from file
        import json
        import yaml
        from pathlib import Path
        
        workflow_file = Path(args.workflow)
        if not workflow_file.exists():
            print(f"❌ Workflow file not found: {workflow_file}")
            return
        
        content = workflow_file.read_text()
        
        if workflow_file.suffix.lower() in ['.yaml', '.yml']:
            workflow_data = yaml.safe_load(content)
        else:
            workflow_data = json.loads(content)
        
        workflow = Workflow.from_dict(workflow_data)
        
        print(f"📋 Running workflow: {workflow.name}")
        print(f"   Tasks: {len(workflow.tasks)}")
        
        # Progress callback
        async def progress_callback(task_id: str, progress: Dict[str, Any]):
            print(f"   🔄 Task progress: {task_id[:8]} - {progress}")
        
        result = await client.submit_workflow(
            workflow,
            timeout=args.timeout,
            progress_callback=progress_callback
        )
        
        if result['status'] == 'completed':
            print(f"\n✅ Workflow completed!")
            print(f"📊 Results:")
            for task_id, task_result in result['results'].items():
                print(f"   {task_id[:8]}: {str(task_result)[:100]}{'...' if len(str(task_result)) > 100 else ''}")
        else:
            print(f"\n❌ Workflow {result['status']}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


async def status_command(args):
    """Handle status command"""
    client = GleitzeitClient(args.server)
    
    try:
        await client.connect()
        
        if args.workflow_id:
            status = await client.get_workflow_status(args.workflow_id)
            print(f"Workflow {args.workflow_id}:")
            print(f"  Status: {status.get('status', 'unknown')}")
            if 'progress' in status:
                progress = status['progress']
                print(f"  Progress: {progress.get('progress_percent', 0):.1f}%")
                print(f"  Tasks: {progress.get('completed', 0)}/{progress.get('total', 0)} completed")
        else:
            print("Server capabilities:", client.server_capabilities)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.disconnect()


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(description="Gleitzeit V2 CLI")
    parser.add_argument('--server', default='http://localhost:8000', help='Server URL')
    parser.add_argument('--timeout', type=float, default=60.0, help='Timeout in seconds')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Text generation
    text_parser = subparsers.add_parser('text', help='Generate text')
    text_parser.add_argument('text', help='Prompt text')
    text_parser.add_argument('--model', default='llama3', help='Model name')
    text_parser.add_argument('--temperature', type=float, default=0.7, help='Temperature')
    text_parser.add_argument('--max-tokens', type=int, default=500, help='Max tokens')
    
    # Vision analysis
    vision_parser = subparsers.add_parser('vision', help='Analyze image')
    vision_parser.add_argument('image', help='Image path')
    vision_parser.add_argument('--prompt', help='Analysis prompt')
    vision_parser.add_argument('--model', default='llava', help='Model name')
    
    # Function execution
    function_parser = subparsers.add_parser('function', help='Execute function')
    function_parser.add_argument('function', help='Function name')
    function_parser.add_argument('args', nargs='*', help='Function arguments (key=value)')
    
    # Workflow execution
    workflow_parser = subparsers.add_parser('workflow', help='Execute workflow')
    workflow_parser.add_argument('workflow', help='Workflow file path')
    
    # Status
    status_parser = subparsers.add_parser('status', help='Get status')
    status_parser.add_argument('workflow_id', nargs='?', help='Workflow ID')
    
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)
    
    if not args.command:
        parser.print_help()
        return
    
    # Run command
    try:
        if args.command == 'text':
            asyncio.run(run_text_command(args))
        elif args.command == 'vision':
            asyncio.run(run_vision_command(args))
        elif args.command == 'function':
            asyncio.run(run_function_command(args))
        elif args.command == 'workflow':
            asyncio.run(run_workflow_command(args))
        elif args.command == 'status':
            asyncio.run(status_command(args))
        else:
            print(f"Unknown command: {args.command}")
    
    except KeyboardInterrupt:
        print("\n🛑 Interrupted")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()