#!/usr/bin/env python3
"""Create 100,000 workflow files efficiently"""

import os

# Create test directory
os.makedirs("test_100k", exist_ok=True)

# Create workflows in batches
for batch in range(100):  # 100 batches of 1000
    print(f"Creating batch {batch+1}/100...")
    for i in range(1000):
        wf_num = batch * 1000 + i + 1
        filename = f"test_100k/wf_{wf_num:06d}.yaml"

        with open(filename, 'w') as f:
            f.write(f"""name: 'Performance Test {wf_num}'
version: '1.0.0'
tasks:
  - id: 'task_1'
    type: 'python'
    method: 'python/execute'
    params:
      code: |
        import time
        start = time.time()
        result = {{
            'workflow_id': {wf_num},
            'calculation': sum(range(100)),
            'duration': time.time() - start
        }}
""")

print("✅ Created 100,000 workflow files in test_100k/")