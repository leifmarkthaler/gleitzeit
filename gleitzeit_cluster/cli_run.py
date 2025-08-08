#!/usr/bin/env python3
"""
Streamlined run command for Gleitzeit CLI

Provides quick execution of tasks and workflows from the command line.
"""

import asyncio
import json
import yaml
from pathlib import Path
from typing import Any, Dict, Optional, List
import os

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
    
    workflow = Workflow(name=f"Quick run: {function_name}")
    workflow.add_task(task)
    
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
    
    workflow = Workflow(name="Quick text generation")
    workflow.add_task(task)
    
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
    
    workflow = Workflow(name="Quick vision analysis")
    workflow.add_task(task)
    
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


async def run_batch_folder(cluster: GleitzeitCluster, folder_path: str, prompt: str, 
                          task_type: str = "vision", model: str = None, 
                          file_extensions: List[str] = None) -> Dict[str, Any]:
    """Execute batch processing on all files in a folder"""
    
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    
    if not folder.is_dir():
        raise ValueError(f"Path is not a directory: {folder_path}")
    
    # Default file extensions based on task type
    if file_extensions is None:
        if task_type == "vision":
            file_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']
        elif task_type == "text":
            file_extensions = ['.txt', '.md', '.csv', '.json', '.yaml', '.yml']
        else:
            file_extensions = []  # All files
    
    # Find all matching files
    matching_files = []
    for file_path in folder.rglob('*'):
        if file_path.is_file():
            if not file_extensions or file_path.suffix.lower() in file_extensions:
                matching_files.append(file_path)
    
    if not matching_files:
        ext_str = ', '.join(file_extensions) if file_extensions else 'any'
        raise ValueError(f"No files found with extensions ({ext_str}) in folder: {folder_path}")
    
    print(f"📦 Found {len(matching_files)} files for batch processing")
    print(f"   Task type: {task_type}")
    print(f"   Model: {model or 'default'}")
    print(f"   Extensions: {', '.join(file_extensions) if file_extensions else 'all'}")
    
    # Create batch workflow
    workflow = Workflow(
        name=f"Batch {task_type} processing: {folder.name}",
        description=f"Process {len(matching_files)} files from {folder_path}"
    )
    
    # Set default model based on task type
    if model is None:
        model = "llava" if task_type == "vision" else "llama3"
    
    # Create tasks for each file
    for i, file_path in enumerate(matching_files):
        relative_path = file_path.relative_to(folder)
        
        if task_type == "vision":
            task = Task(
                id=f"process_{i}",
                name=f"Analyze {relative_path}",
                task_type=TaskType.VISION,
                parameters=TaskParameters(
                    image_path=str(file_path),
                    prompt=prompt,
                    model_name=model
                )
            )
        elif task_type == "text":
            # For text files, read content and include in prompt
            file_prompt = f"{prompt}\n\nFile: {relative_path}\nContent: {{file_content}}"
            task = Task(
                id=f"process_{i}",
                name=f"Process {relative_path}",
                task_type=TaskType.TEXT,
                parameters=TaskParameters(
                    prompt=file_prompt,
                    model_name=model,
                    file_path=str(file_path)  # Will be read by executor
                )
            )
        elif task_type == "function":
            # For function tasks, pass file path as argument
            task = Task(
                id=f"process_{i}",
                name=f"Process {relative_path}",
                task_type=TaskType.FUNCTION,
                parameters=TaskParameters(
                    function_name=prompt,  # Function name passed as prompt
                    kwargs={"file_path": str(file_path)}
                )
            )
        else:
            raise ValueError(f"Unsupported batch task type: {task_type}")
        
        workflow.add_task(task)
    
    # Add aggregation task to collect all results
    aggregation_task = Task(
        id="aggregate_results",
        name="Aggregate Batch Results",
        task_type=TaskType.FUNCTION,
        parameters=TaskParameters(
            function_name="aggregate",
            kwargs={
                "operation": "collect",
                "results": {f"process_{i}": f"{{{{process_{i}.result}}}}" for i in range(len(matching_files))},
                "metadata": {
                    "folder": str(folder),
                    "total_files": len(matching_files),
                    "task_type": task_type,
                    "model": model
                }
            }
        ),
        dependencies=[f"process_{i}" for i in range(len(matching_files))]
    )
    workflow.add_task(aggregation_task)
    
    # Submit workflow
    workflow_id = await cluster.submit_workflow(workflow)
    print(f"🚀 Started batch processing workflow: {workflow_id}")
    
    # Monitor progress
    completed_files = set()
    while True:
        status = await cluster.get_workflow_status(workflow_id)
        
        # Show progress for completed files  
        completed_tasks_data = status.get("completed_tasks", [])
        if isinstance(completed_tasks_data, int):
            # If it's just a count, we can't track individual completed tasks
            current_completed = set()
        else:
            current_completed = set(completed_tasks_data)
        new_completed = current_completed - completed_files
        
        for task_id in new_completed:
            if task_id.startswith("process_"):
                file_index = int(task_id.split("_")[1])
                if file_index < len(matching_files):
                    file_name = matching_files[file_index].name
                    print(f"   ✅ Completed: {file_name}")
        
        completed_files = current_completed
        
        if status["status"] in ["completed", "failed"]:
            break
        
        await asyncio.sleep(2)
    
    if status["status"] == "completed":
        results = status.get("task_results", {})
        
        # Extract individual file results
        file_results = {}
        for i, file_path in enumerate(matching_files):
            task_id = f"process_{i}"
            if task_id in results:
                relative_path = file_path.relative_to(folder)
                file_results[str(relative_path)] = results[task_id]
        
        # Get aggregated results if available
        aggregated = results.get("aggregate_results", {})
        
        print(f"\n✅ Batch processing completed!")
        print(f"   Processed: {len(file_results)} files")
        print(f"   Success rate: {len(file_results)}/{len(matching_files)} ({len(file_results)/len(matching_files)*100:.1f}%)")
        
        return {
            "summary": {
                "folder": str(folder),
                "total_files": len(matching_files),
                "processed_files": len(file_results),
                "success_rate": len(file_results)/len(matching_files),
                "task_type": task_type,
                "model": model
            },
            "results": file_results,
            "aggregated": aggregated
        }
    else:
        error = status.get("error", "Unknown error")
        print(f"❌ Batch processing failed: {error}")
        raise RuntimeError(f"Batch processing failed: {error}")


def discover_batch_files(folder_path: str, task_type: str = None, max_preview: int = 5) -> Dict[str, Any]:
    """Discover and preview files in a folder for batch processing"""
    
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    
    # File type mappings
    file_types = {
        "vision": {
            "extensions": ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.svg'],
            "description": "Image files"
        },
        "text": {
            "extensions": ['.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.log'],
            "description": "Text files"
        },
        "document": {
            "extensions": ['.pdf', '.doc', '.docx', '.rtf'],
            "description": "Document files"
        },
        "code": {
            "extensions": ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs'],
            "description": "Code files"
        }
    }
    
    # Discover all files by type
    discovered = {}
    total_files = 0
    
    for category, info in file_types.items():
        matching_files = []
        for file_path in folder.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in info["extensions"]:
                matching_files.append(file_path)
        
        if matching_files:
            # Sort by name for consistent ordering
            matching_files.sort(key=lambda x: x.name)
            
            discovered[category] = {
                "count": len(matching_files),
                "description": info["description"],
                "extensions": info["extensions"],
                "preview": [f.name for f in matching_files[:max_preview]],
                "total_size": sum(f.stat().st_size for f in matching_files if f.exists())
            }
            total_files += len(matching_files)
    
    return {
        "folder": str(folder),
        "total_files": total_files,
        "categories": discovered,
        "suggested_commands": generate_batch_commands(folder_path, discovered)
    }


def generate_batch_commands(folder_path: str, discovered: Dict[str, Any]) -> List[str]:
    """Generate suggested batch processing commands"""
    
    commands = []
    folder_name = Path(folder_path).name
    
    for category, info in discovered.items():
        if info["count"] > 0:
            if category == "vision":
                commands.append(
                    f'gleitzeit run --batch-folder "{folder_path}" --prompt "Describe this image" --type vision'
                )
                commands.append(
                    f'gleitzeit run --batch-folder "{folder_path}" --prompt "Extract text from this image" --type vision --model llava'
                )
            elif category == "text":
                commands.append(
                    f'gleitzeit run --batch-folder "{folder_path}" --prompt "Summarize this content" --type text'
                )
                commands.append(
                    f'gleitzeit run --batch-folder "{folder_path}" --prompt "count_words" --type function'
                )
    
    return commands


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
    
    workflow = Workflow(
        name=data.get("name", "Workflow"),
        description=data.get("description", "")
    )
    
    for task in tasks:
        workflow.add_task(task)
    
    return workflow


async def run_command_handler(args):
    """Handle the run command from CLI"""
    
    # Handle folder discovery first (doesn't need cluster)
    if hasattr(args, 'discover') and args.discover:
        discovery = discover_batch_files(args.discover)
        print(f"📂 Folder Analysis: {discovery['folder']}")
        print(f"   Total files: {discovery['total_files']}")
        print()
        
        for category, info in discovery['categories'].items():
            print(f"📁 {info['description']}: {info['count']} files")
            if info['preview']:
                preview = ', '.join(info['preview'])
                if len(info['preview']) < info['count']:
                    preview += f", ... (+{info['count'] - len(info['preview'])} more)"
                print(f"   Files: {preview}")
            print()
        
        if discovery['suggested_commands']:
            print("💡 Suggested batch commands:")
            for cmd in discovery['suggested_commands']:
                print(f"   {cmd}")
        
        return
    
    # Start cluster connection for execution tasks
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_real_execution=False
    )
    
    try:
        await cluster.start()
        
        # Determine what to run
        if hasattr(args, 'batch_folder') and args.batch_folder:
            # Run batch folder processing
            task_type = getattr(args, 'type', 'vision')
            prompt = args.prompt or ("Describe this image" if task_type == "vision" else "Analyze this content")
            model = getattr(args, 'model', None)
            extensions = getattr(args, 'extensions', None)
            
            if extensions:
                extensions = [ext.strip() for ext in extensions.split(',')]
            
            results = await run_batch_folder(
                cluster, 
                args.batch_folder, 
                prompt, 
                task_type, 
                model, 
                extensions
            )
            
            print(f"\n📊 Batch Results Summary:")
            summary = results['summary']
            print(f"   Folder: {summary['folder']}")
            print(f"   Files processed: {summary['processed_files']}/{summary['total_files']}")
            print(f"   Success rate: {summary['success_rate']:.1%}")
            print(f"   Task type: {summary['task_type']}")
            print(f"   Model: {summary['model']}")
            
            # Show sample results
            if results['results']:
                print(f"\n📋 Sample Results:")
                for i, (file_path, result) in enumerate(list(results['results'].items())[:3]):
                    print(f"   {file_path}: {str(result)[:100]}{'...' if len(str(result)) > 100 else ''}")
                
                if len(results['results']) > 3:
                    print(f"   ... and {len(results['results']) - 3} more results")
        
        elif args.function:
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