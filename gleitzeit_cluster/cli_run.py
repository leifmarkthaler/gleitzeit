#!/usr/bin/env python3
"""
Streamlined run command for Gleitzeit CLI

Provides quick execution of tasks and workflows from the command line.
"""

import asyncio
import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from .core.workflow import Workflow
from .core.task import Task, TaskType, TaskParameters
from .core.cluster import GleitzeitCluster


async def run_function(cluster: GleitzeitCluster, function_name: str, **kwargs) -> Any:
    """Execute a single function task"""
    
    task = Task(
        name=f"Run {function_name}",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name=function_name,
            kwargs=kwargs
        )
    )
    
    workflow = Workflow(
        name=f"Quick run: {function_name}",
        tasks=[task]
    )
    
    # Submit and wait
    workflow_id = await cluster.submit_workflow(workflow)
    print(f"⚡ Running function: {function_name}")
    
    # Wait for completion
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        if status["status"] in ["completed", "failed"]:
            break
        await asyncio.sleep(0.5)
    
    if status["status"] == "completed":
        results = status.get("task_results", {})
        if task.id in results:
            return results[task.id]
    else:
        error = status.get("error", "Unknown error")
        raise RuntimeError(f"Task failed: {error}")


async def run_text(cluster: GleitzeitCluster, prompt: str, model: str = "llama3") -> str:
    """Execute a text generation task"""
    
    task = Task(
        name="Text generation",
        task_type=TaskType.TEXT,
        parameters=TaskParameters(
            prompt=prompt,
            model_name=model
        )
    )
    
    workflow = Workflow(
        name="Quick text generation",
        tasks=[task]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    print(f"💬 Generating text with {model}...")
    
    # Wait for completion
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        if status["status"] in ["completed", "failed"]:
            break
        await asyncio.sleep(0.5)
    
    if status["status"] == "completed":
        results = status.get("task_results", {})
        if task.id in results:
            return results[task.id]
    else:
        error = status.get("error", "Unknown error")
        raise RuntimeError(f"Text generation failed: {error}")


async def run_vision(cluster: GleitzeitCluster, image_path: str, prompt: str, model: str = "llava") -> str:
    """Execute a vision analysis task"""
    
    task = Task(
        name="Vision analysis",
        task_type=TaskType.VISION,
        parameters=TaskParameters(
            image_path=image_path,
            prompt=prompt,
            model_name=model
        )
    )
    
    workflow = Workflow(
        name="Quick vision analysis",
        tasks=[task]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    print(f"👁️ Analyzing image with {model}...")
    
    # Wait for completion
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        if status["status"] in ["completed", "failed"]:
            break
        await asyncio.sleep(0.5)
    
    if status["status"] == "completed":
        results = status.get("task_results", {})
        if task.id in results:
            return results[task.id]
    else:
        error = status.get("error", "Unknown error")
        raise RuntimeError(f"Vision analysis failed: {error}")


async def run_workflow_file(cluster: GleitzeitCluster, workflow_file: Path) -> Dict[str, Any]:
    """Execute a workflow from YAML/JSON file"""
    
    # Load workflow definition
    content = workflow_file.read_text()
    
    if workflow_file.suffix in ['.yaml', '.yml']:
        workflow_def = yaml.safe_load(content)
    elif workflow_file.suffix == '.json':
        workflow_def = json.loads(content)
    else:
        raise ValueError(f"Unsupported file format: {workflow_file.suffix}")
    
    # Create workflow from definition
    workflow = create_workflow_from_dict(workflow_def)
    
    # Submit workflow
    workflow_id = await cluster.submit_workflow(workflow)
    print(f"📋 Running workflow: {workflow.name}")
    print(f"   ID: {workflow_id}")
    
    # Monitor progress
    last_status = None
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        current_status = status["status"]
        
        if current_status != last_status:
            completed = len(status.get("completed_tasks", []))
            total = len(workflow.tasks)
            print(f"   Status: {current_status} ({completed}/{total} tasks)")
            last_status = current_status
        
        if current_status in ["completed", "failed"]:
            break
        
        await asyncio.sleep(1)
    
    if status["status"] == "completed":
        print("✅ Workflow completed successfully")
        return status.get("task_results", {})
    else:
        error = status.get("error", "Unknown error")
        print(f"❌ Workflow failed: {error}")
        raise RuntimeError(f"Workflow failed: {error}")


def create_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """Create workflow from dictionary definition"""
    
    tasks = []
    for task_def in data.get("tasks", []):
        # Determine task type
        if "function" in task_def:
            task_type = TaskType.FUNCTION
            params = TaskParameters(
                function_name=task_def["function"],
                kwargs=task_def.get("args", {})
            )
        elif "prompt" in task_def and "image" in task_def:
            task_type = TaskType.VISION
            params = TaskParameters(
                prompt=task_def["prompt"],
                image_path=task_def["image"],
                model_name=task_def.get("model", "llava")
            )
        elif "prompt" in task_def:
            task_type = TaskType.TEXT
            params = TaskParameters(
                prompt=task_def["prompt"],
                model_name=task_def.get("model", "llama3")
            )
        elif "url" in task_def:
            task_type = TaskType.HTTP
            params = TaskParameters(
                url=task_def["url"],
                method=task_def.get("method", "GET"),
                headers=task_def.get("headers", {}),
                data=task_def.get("data")
            )
        elif "file" in task_def:
            task_type = TaskType.FILE
            params = TaskParameters(
                operation=task_def.get("operation", "read"),
                source_path=task_def.get("file"),
                target_path=task_def.get("target"),
                content=task_def.get("content")
            )
        else:
            raise ValueError(f"Cannot determine task type for: {task_def}")
        
        task = Task(
            id=task_def.get("id", f"task_{len(tasks) + 1}"),
            name=task_def.get("name", f"Task {len(tasks) + 1}"),
            task_type=task_type,
            parameters=params,
            dependencies=task_def.get("dependencies", [])
        )
        tasks.append(task)
    
    return Workflow(
        name=data.get("name", "Workflow"),
        description=data.get("description", ""),
        tasks=tasks
    )


async def run_command_handler(args):
    """Handle the run command from CLI"""
    
    # Start cluster connection
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_real_execution=False
    )
    
    try:
        await cluster.start()
        
        # Determine what to run
        if args.function:
            # Run a function
            kwargs = {}
            if args.args:
                # Parse key=value arguments
                for arg in args.args:
                    if '=' in arg:
                        key, value = arg.split('=', 1)
                        # Try to parse as JSON, fallback to string
                        try:
                            kwargs[key] = json.loads(value)
                        except:
                            kwargs[key] = value
                    else:
                        raise ValueError(f"Invalid argument format: {arg}. Use key=value")
            
            result = await run_function(cluster, args.function, **kwargs)
            print(f"\n📊 Result:")
            if isinstance(result, (dict, list)):
                print(json.dumps(result, indent=2))
            else:
                print(result)
        
        elif args.text:
            # Run text generation
            result = await run_text(cluster, args.text, args.model or "llama3")
            print(f"\n📝 Generated text:")
            print(result)
        
        elif args.vision:
            # Run vision analysis
            if not args.prompt:
                args.prompt = "Describe what you see in this image"
            result = await run_vision(cluster, args.vision, args.prompt, args.model or "llava")
            print(f"\n👁️ Vision analysis:")
            print(result)
        
        elif args.workflow:
            # Run workflow file
            workflow_file = Path(args.workflow)
            if not workflow_file.exists():
                raise FileNotFoundError(f"Workflow file not found: {workflow_file}")
            
            results = await run_workflow_file(cluster, workflow_file)
            print(f"\n📊 Results:")
            print(json.dumps(results, indent=2, default=str))
        
        else:
            print("❌ No task specified. Use --help for options.")
    
    finally:
        await cluster.stop()