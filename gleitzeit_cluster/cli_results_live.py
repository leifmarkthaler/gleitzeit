"""
Live Results CLI - Fetch real-time results from Redis
"""

import asyncio
import json
from typing import Optional, Dict, Any
from datetime import datetime

from .storage.redis_client import RedisClient


async def show_live_workflow_result(workflow_id: str, redis_client: RedisClient) -> None:
    """Show live workflow result from Redis"""
    
    print(f"🔍 Fetching live result for workflow: {workflow_id}")
    print("=" * 50)
    
    # Get workflow details
    workflow_data = await redis_client.redis.hgetall(f"workflow:{workflow_id}")
    
    if not workflow_data:
        print("❌ Workflow not found")
        return
    
    # Display workflow info
    print("\n📋 Workflow Details:")
    print(f"   ID: {workflow_id}")
    print(f"   Name: {workflow_data.get('name', 'Unknown')}")
    print(f"   Status: {workflow_data.get('status', 'Unknown')}")
    print(f"   Created: {workflow_data.get('created_at', 'Unknown')}")
    
    # Get tasks for this workflow (excluding dependency keys)
    all_task_keys = await redis_client.redis.keys("task:*")
    # Filter out dependency keys that have different data types
    task_keys = [key for key in all_task_keys if not key.endswith(':dependencies')]
    workflow_tasks = []
    
    for task_key in task_keys:
        try:
            task_data = await redis_client.redis.hgetall(task_key)
            if task_data and task_data.get('workflow_id') == workflow_id:
                task_id = task_key.split(':')[1]
                workflow_tasks.append({
                    'id': task_id,
                    'data': task_data
                })
        except Exception as e:
            # Skip any other problematic keys
            continue
    
    print(f"\n📊 Tasks: {len(workflow_tasks)} found")
    
    # Display task results
    for task in workflow_tasks:
        task_data = task['data']
        task_id = task['id']
        
        print(f"\n📄 Task: {task_data.get('name', task_id[:8])}...")
        print(f"   Status: {task_data.get('status', 'Unknown')}")
        print(f"   Type: {task_data.get('task_type', 'Unknown')}")
        
        # Get and display result
        result_str = task_data.get('result')
        if result_str:
            try:
                result = json.loads(result_str)
                
                # For LLM responses
                if 'response' in result:
                    print(f"\n   🤖 LLM Response:")
                    print("   " + "-" * 40)
                    response_text = result['response']
                    # Display response with proper indentation
                    for line in response_text.split('\n'):
                        print(f"   {line}")
                    print("   " + "-" * 40)
                    
                    # Show model info if available
                    if 'model' in result:
                        print(f"   Model: {result['model']}")
                    if 'done' in result:
                        print(f"   Completed: {result['done']}")
                
                # For other result types
                elif isinstance(result, dict):
                    print(f"\n   📦 Result:")
                    for key, value in result.items():
                        if key != 'context':  # Skip large context arrays
                            print(f"      {key}: {str(value)[:100]}")
                else:
                    print(f"\n   📦 Result: {str(result)[:500]}")
                    
            except json.JSONDecodeError:
                print(f"\n   📦 Result (raw): {result_str[:500]}")
        
        # Show error if any
        error = task_data.get('error')
        if error:
            print(f"\n   ❌ Error: {error}")
    
    # Get workflow results collection
    workflow_results = await redis_client.redis.hgetall(f"workflow:results:{workflow_id}")
    if workflow_results:
        print(f"\n📈 Workflow Results Summary:")
        for task_id, result in workflow_results.items():
            print(f"   {task_id[:8]}...: {result[:100]}...")


async def list_live_workflows(redis_client: RedisClient, limit: int = 10) -> None:
    """List recent workflows from Redis"""
    
    print("📋 Listing live workflows...")
    print("=" * 50)
    
    # Get all workflow keys
    workflow_keys = await redis_client.redis.keys("workflow:*")
    
    # Filter out results and other sub-keys
    workflow_ids = []
    for key in workflow_keys:
        if ':' not in key.split('workflow:')[1]:  # Only base workflow keys
            workflow_ids.append(key)
    
    # Sort by creation time and limit
    workflows = []
    for wf_key in workflow_ids[:limit * 2]:  # Get extra to account for filtering
        wf_data = await redis_client.redis.hgetall(wf_key)
        if wf_data:
            wf_id = wf_key.split(':')[1]
            workflows.append({
                'id': wf_id,
                'data': wf_data
            })
    
    # Sort by created_at
    workflows.sort(
        key=lambda x: x['data'].get('created_at', ''), 
        reverse=True
    )
    
    # Display workflows
    print(f"\nShowing {min(len(workflows), limit)} most recent workflows:\n")
    print(f"{'ID':<40} {'Name':<20} {'Status':<12} {'Created'}")
    print("-" * 90)
    
    for wf in workflows[:limit]:
        wf_id = wf['id']
        wf_data = wf['data']
        name = wf_data.get('name', 'Unknown')[:20]
        status = wf_data.get('status', 'Unknown')
        created = wf_data.get('created_at', 'Unknown')
        
        # Format created date
        if created != 'Unknown':
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                created = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
        
        print(f"{wf_id:<40} {name:<20} {status:<12} {created}")
    
    print("\n💡 Use 'gleitzeit results show <workflow_id>' to see details")
    print("💡 Or use 'gleitzeit results show --name <workflow_name>' to search by name")


async def find_workflow_by_name(workflow_name: str, redis_client: RedisClient) -> Optional[str]:
    """Find workflow ID by name (supports partial matching)"""
    
    # Get all workflow keys
    workflow_keys = await redis_client.redis.keys("workflow:*")
    
    # Filter out results and other sub-keys
    workflow_ids = []
    for key in workflow_keys:
        if ':' not in key.split('workflow:')[1]:  # Only base workflow keys
            workflow_ids.append(key)
    
    matches = []
    
    # Search for workflows with matching names
    for wf_key in workflow_ids:
        wf_data = await redis_client.redis.hgetall(wf_key)
        if wf_data:
            wf_id = wf_key.split(':')[1]
            name = wf_data.get('name', '')
            
            # Exact match (case insensitive)
            if name.lower() == workflow_name.lower():
                return wf_id
            
            # Partial match (case insensitive)
            if workflow_name.lower() in name.lower():
                matches.append({
                    'id': wf_id,
                    'name': name,
                    'created': wf_data.get('created_at', 'Unknown')
                })
    
    # If we have matches, show them and ask for clarification
    if matches:
        if len(matches) == 1:
            print(f"📋 Found workflow: {matches[0]['name']}")
            return matches[0]['id']
        else:
            print(f"📋 Found {len(matches)} workflows matching '{workflow_name}':")
            print()
            print(f"{'ID':<40} {'Name':<30} {'Created'}")
            print("-" * 80)
            
            for match in matches:
                created = match['created']
                if created != 'Unknown':
                    try:
                        dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        created = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass
                        
                print(f"{match['id']:<40} {match['name']:<30} {created}")
            
            print("\n💡 Use the specific workflow ID from above")
            return None
    
    return None


async def live_results_command(args):
    """Enhanced results command with live data"""
    
    # Connect to Redis
    redis_client = RedisClient()
    try:
        await redis_client.connect()
        print("✅ Connected to Redis")
        
        if args.results_command == 'show':
            workflow_id = None
            
            # Check if we have a name parameter
            if hasattr(args, 'name') and args.name:
                workflow_id = await find_workflow_by_name(args.name, redis_client)
                if not workflow_id:
                    print(f"❌ No workflow found with name '{args.name}'")
                    return
            elif args.workflow_id:
                workflow_id = args.workflow_id
            else:
                print("❌ Please specify either workflow_id or --name <workflow_name>")
                return
            
            await show_live_workflow_result(workflow_id, redis_client)
        elif args.results_command == 'list':
            limit = getattr(args, 'limit', 10)
            await list_live_workflows(redis_client, limit)
        else:
            # Fall back to original cache-based command
            from .storage.result_cache import ResultCache
            cache = ResultCache(redis_client=redis_client)
            
            if args.results_command == 'show':
                # First try live, then cache
                await show_live_workflow_result(args.workflow_id, redis_client)
            else:
                print("Using cached results...")
                # Original cache logic
                pass
                
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await redis_client.disconnect()
        print("🔌 Disconnected from Redis")