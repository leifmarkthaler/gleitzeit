#!/usr/bin/env python3
"""Test the log streaming system end-to-end"""
import asyncio
import json
import aiohttp
import websockets

async def submit_task():
    """Submit a Python task to Gleitzeit"""
    async with aiohttp.ClientSession() as session:
        # Submit a Python task
        task_data = {
            "id": f"log-test-task-001",
            "name": "Test Log Streaming Task",
            "protocol": "python/v1",
            "method": "python/execute",
            "params": {
                "file": "/Users/leifmarkthaler/github/gleitzeit 0.0.6/test_log_output.py"
            }
        }
        
        async with session.post('http://localhost:8000/tasks', json=task_data) as resp:
            result = await resp.json()
            print(f"Task submitted: {result}")
            return result.get('id') or result.get('task_id')

async def stream_logs(task_id):
    """Connect to WebSocket and stream logs for a task"""
    uri = f"ws://localhost:8000/ws/logs/task/{task_id}"
    print(f"Connecting to WebSocket: {uri}")
    
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to log stream!")
            
            # Listen for logs
            while True:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    data = json.loads(message)
                    
                    msg_type = data.get('type')
                    msg_data = data.get('data', {})
                    
                    if msg_type == 'log:subscribed':
                        print(f"✓ Subscribed to stream: {data.get('stream')}")
                        print(f"  Buffered logs: {data.get('buffered_count')}")
                    elif msg_type == 'log:history':
                        print(f"[HISTORY] {msg_data.get('level', 'INFO')}: {msg_data.get('message', '')}")
                    elif msg_type == 'log:message':
                        level = msg_data.get('level', 'INFO')
                        message = msg_data.get('message', '')
                        source = msg_data.get('source', 'UNKNOWN')
                        stream_type = msg_data.get('stream_type', '')
                        
                        if stream_type:
                            print(f"[{level}][{source}][{stream_type}] {message}")
                        else:
                            print(f"[{level}][{source}] {message}")
                    elif msg_type == 'log:stream_start':
                        print(f"--- Stream started for task {msg_data.get('task_id')} ---")
                    elif msg_type == 'log:stream_end':
                        print(f"--- Stream ended for task {msg_data.get('task_id')} ---")
                        break
                    else:
                        print(f"Unknown message type: {msg_type}")
                        
                except asyncio.TimeoutError:
                    print("No logs received for 10 seconds, closing connection")
                    break
                    
    except Exception as e:
        print(f"WebSocket error: {e}")

async def check_task_status(task_id):
    """Check the final status of the task"""
    await asyncio.sleep(1)  # Give it a moment to complete
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f'http://localhost:8000/tasks/{task_id}') as resp:
            result = await resp.json()
            print(f"\nFinal task status: {result.get('status')}")
            if result.get('result'):
                print(f"Task result: {json.dumps(result['result'], indent=2)}")
            if result.get('error'):
                print(f"Task error: {result['error']}")

async def main():
    """Main test function"""
    print("Testing Gleitzeit Log Streaming System")
    print("=" * 50)
    
    # Submit task
    task_id = await submit_task()
    
    if not task_id:
        print("Failed to submit task")
        return
    
    # Stream logs in parallel with task execution
    await stream_logs(task_id)
    
    # Check final status
    await check_task_status(task_id)
    
    print("\nLog streaming test completed!")

if __name__ == "__main__":
    asyncio.run(main())