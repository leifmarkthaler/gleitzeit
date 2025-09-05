#!/usr/bin/env python3
"""Verify dependency execution order"""

import asyncio
import sys
import os
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit import Client, ClientMode, Task, Workflow

# Create a log file to track execution order
LOG_FILE = "task_execution.log"

def create_task_file(task_id: str, deps: list = None):
    """Create a Python file that logs when it executes"""
    deps_str = f" (depends on {deps})" if deps else ""
    content = f'''
import os
from datetime import datetime

log_file = "{LOG_FILE}"
with open(log_file, "a") as f:
    f.write(f"{{datetime.now().isoformat()}} - Task {task_id} executed{deps_str}\\n")
print("Task {task_id} executed{deps_str}")
'''
    Path(f"task_{task_id}.py").write_text(content)

async def main():
    print("🧪 Testing workflow dependency execution order...")
    
    # Clear log file
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)
    
    # Create task files
    create_task_file("1")
    create_task_file("2", ["1"])
    create_task_file("3", ["2"])
    create_task_file("4", ["1"])
    create_task_file("5", ["3", "4"])
    
    # Create client
    client = Client(mode=ClientMode.NATIVE)
    await client.initialize()
    print("✅ Client initialized")
    
    # Create workflow with complex dependencies
    workflow = Workflow(
        id="dep_order_test",
        name="Dependency Order Test",
        tasks=[
            Task(id="t1", name="Task 1", protocol="python/v1", method="python/execute", 
                 params={"file": "task_1.py"}),
            Task(id="t2", name="Task 2", protocol="python/v1", method="python/execute",
                 dependencies=["t1"], params={"file": "task_2.py"}),
            Task(id="t3", name="Task 3", protocol="python/v1", method="python/execute",
                 dependencies=["t2"], params={"file": "task_3.py"}),
            Task(id="t4", name="Task 4", protocol="python/v1", method="python/execute",
                 dependencies=["t1"], params={"file": "task_4.py"}),
            Task(id="t5", name="Task 5", protocol="python/v1", method="python/execute",
                 dependencies=["t3", "t4"], params={"file": "task_5.py"})
        ]
    )
    
    print("📝 Workflow structure:")
    print("   t1 ──> t2 ──> t3 ──┐")
    print("    └──> t4 ─────────> t5")
    
    # Submit workflow
    print("\n📤 Submitting workflow...")
    await client.submit_workflow(workflow)
    
    # Wait for execution
    print("⏳ Waiting for execution...")
    await asyncio.sleep(5)
    
    # Check workflow status
    wf = await client.get_workflow("dep_order_test")
    if wf:
        print(f"\n✅ Workflow status: {wf.status}")
        
        # Check task statuses
        completed = 0
        for task in wf.tasks:
            print(f"   Task {task.id}: {task.status}")
            if task.status == "completed":
                completed += 1
        
        if completed == 5:
            print("\n🎉 All tasks completed!")
            
            # Check execution order from log
            if os.path.exists(LOG_FILE):
                print("\n📋 Execution order:")
                with open(LOG_FILE) as f:
                    for line in f:
                        print(f"   {line.strip()}")
                
                # Verify order
                lines = open(LOG_FILE).readlines()
                order = [line.split("Task ")[1].split(" ")[0] for line in lines]
                print(f"\n📊 Order: {' -> '.join(order)}")
                
                # Check constraints
                valid = True
                if order.index("1") > order.index("2"):
                    print("❌ Task 2 ran before Task 1!")
                    valid = False
                if order.index("2") > order.index("3"):
                    print("❌ Task 3 ran before Task 2!")
                    valid = False
                if order.index("1") > order.index("4"):
                    print("❌ Task 4 ran before Task 1!")
                    valid = False
                if "3" in order and "4" in order and "5" in order:
                    if order.index("3") > order.index("5") or order.index("4") > order.index("5"):
                        print("❌ Task 5 ran before its dependencies!")
                        valid = False
                
                if valid:
                    print("\n✅ Dependencies were respected!")
                else:
                    print("\n❌ Dependency order violated!")
        else:
            print(f"\n❌ Only {completed}/5 tasks completed")
    
    await client.shutdown()
    
    # Cleanup
    for i in range(1, 6):
        Path(f"task_{i}.py").unlink(missing_ok=True)

if __name__ == "__main__":
    asyncio.run(main())