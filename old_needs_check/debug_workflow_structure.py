#!/usr/bin/env python3
"""
Debug script to compare workflow structures between YAML and Easy Client
"""
import json
import yaml
from gleitzeit.easy import t, w

# Create Easy Client workflow structure
generate = t("generate", "python/v1:execute").with_(code="""
result = {
    'number': 42,
    'message': 'Hello from generate task'
}
print(f'Generated: {result}')
""")

process = t("process", "python/v1:execute").input(generate).with_(code="""
# 'generate' variable is automatically available
print(f'Received from generate task: {generate}')
result = {
    'doubled': generate.get('number', 0) * 2,
    'response': f"Processed: {generate.get('message', 'none')}"
}
print(f'Processed result: {result}')
""")

workflow = w(generate).sequential(process).name("debug_structure")

# Get the Easy Client workflow dict
easy_workflow = workflow.to_dict()

print("=" * 80)
print("EASY CLIENT WORKFLOW STRUCTURE")
print("=" * 80)
print(json.dumps(easy_workflow, indent=2))
print()

# Load YAML workflow structure
with open('test_yaml_chaining.yaml', 'r') as f:
    yaml_workflow = yaml.safe_load(f)

print("=" * 80)
print("YAML WORKFLOW STRUCTURE")
print("=" * 80)
print(json.dumps(yaml_workflow, indent=2))
print()

# Compare the tasks
print("=" * 80)
print("COMPARISON: 'process' task params")
print("=" * 80)

easy_process_task = None
for task in easy_workflow.get('tasks', []):
    if task.get('name') == 'process':
        easy_process_task = task
        break

yaml_process_task = None
for task in yaml_workflow.get('tasks', []):
    if task.get('name') == 'process':
        yaml_process_task = task
        break

print("\nEasy Client 'process' task:")
print(json.dumps(easy_process_task, indent=2))

print("\nYAML 'process' task:")
print(json.dumps(yaml_process_task, indent=2))

print("\n" + "=" * 80)
print("KEY DIFFERENCES")
print("=" * 80)

if easy_process_task and yaml_process_task:
    easy_params = easy_process_task.get('params', {})
    yaml_params = yaml_process_task.get('params', {})

    print("\nEasy Client params keys:", list(easy_params.keys()))
    print("YAML params keys:", list(yaml_params.keys()))

    print("\nEasy Client 'inputs' type:", type(easy_params.get('inputs')))
    print("Easy Client 'inputs' value:", easy_params.get('inputs'))

    print("\nYAML 'inputs' type:", type(yaml_params.get('inputs')))
    print("YAML 'inputs' value:", yaml_params.get('inputs'))
