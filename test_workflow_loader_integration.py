#!/usr/bin/env python
"""
Test that WorkflowLoaderWorkerV2 properly handles workflow tasks.
"""

import sys
from pathlib import Path
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from gleitzeit.handlers import handler_loader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load all handlers
capabilities = handler_loader.get_all_capabilities()

print("\nRegistered Handlers:")
print("="*60)

for protocol, caps in capabilities.items():
    print(f"\nProtocol: {protocol}")
    print(f"  Task types: {caps.get('task_types', [])}")
    print(f"  Methods:")
    for method, details in caps.get('methods', {}).items():
        print(f"    - {method}: {details.get('description', 'No description')}")

# Check if workflow handler is registered
if 'workflow/v1' in capabilities:
    print("\n✅ WorkflowHandler is registered!")
    workflow_caps = capabilities['workflow/v1']
    print(f"\nWorkflow task types: {workflow_caps['task_types']}")
    print(f"Workflow methods: {list(workflow_caps['methods'].keys())}")
else:
    print("\n❌ WorkflowHandler NOT found!")

# Test type-to-protocol mapping
print("\n" + "="*60)
print("Testing type-to-protocol mapping:")

type_to_protocol = {}
for protocol, caps in capabilities.items():
    for task_type in caps.get('task_types', []):
        if task_type not in type_to_protocol:
            type_to_protocol[task_type] = protocol

print(f"\nType mappings:")
for task_type, protocol in sorted(type_to_protocol.items()):
    print(f"  {task_type:20} -> {protocol}")

if 'workflow' in type_to_protocol:
    print(f"\n✅ 'workflow' type maps to: {type_to_protocol['workflow']}")
else:
    print("\n❌ 'workflow' type NOT mapped!")

# Test method resolution
print("\n" + "="*60)
print("Testing method resolution for workflow task:")

raw_task = {
    'id': 'test_workflow',
    'type': 'workflow',
    'method': 'workflow/execute',
    'params': {
        'workflow_ref': 'test.yaml',
        'inputs': {'key': 'value'}
    }
}

task_type = raw_task.get('type')
method = raw_task.get('method')

if task_type in type_to_protocol:
    protocol = type_to_protocol[task_type]
    print(f"\nTask type '{task_type}' -> protocol '{protocol}'")
    print(f"Method: {method}")
    
    if protocol in capabilities:
        methods = capabilities[protocol].get('methods', {})
        if method in methods:
            print(f"\n✅ Method '{method}' is valid for protocol '{protocol}'")
            print(f"   Description: {methods[method].get('description')}")
        else:
            print(f"\n❌ Method '{method}' NOT found in protocol '{protocol}'")
            print(f"   Available methods: {list(methods.keys())}")
else:
    print(f"\n❌ Task type '{task_type}' not recognized")