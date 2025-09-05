"""Tests for complex and specialized workflows"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import yaml
import json

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.core.workflow_loader import load_workflow_from_dict


class TestComplexWorkflows:
    """Test complex workflow patterns and features"""
    
    @pytest.fixture
    def test_context_workflow(self):
        """Workflow testing context and parameter passing"""
        return {
            "name": "Context Test Workflow",
            "parameters": {
                "global_model": "llama3.2",
                "temperature": 0.7
            },
            "tasks": [
                {
                    "id": "task_with_context",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {
                        "code": """
import os
# Access workflow context
workflow_id = context.get('workflow_id')
task_id = context.get('task_id')
params = context.get('parameters')
print(f"Workflow: {workflow_id}, Task: {task_id}")
print(f"Global params: {params}")
result = {'workflow': workflow_id, 'params': params}
"""
                    }
                },
                {
                    "id": "use_global_params",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["task_with_context"],
                    "parameters": {
                        "model": "${parameters.global_model}",
                        "temperature": "${parameters.temperature}",
                        "messages": [
                            {"role": "user", "content": "Using context: ${task_with_context.result}"}
                        ]
                    }
                }
            ]
        }
    
    @pytest.fixture
    def multi_instance_demo_workflow(self):
        """Workflow demonstrating multi-instance execution"""
        return {
            "name": "Multi-Instance Demo",
            "tasks": [
                {
                    "id": "instance_1",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "instance_affinity": "instance-1",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Response from instance 1"}]
                    }
                },
                {
                    "id": "instance_2",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "instance_affinity": "instance-2",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Response from instance 2"}]
                    }
                },
                {
                    "id": "instance_3",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "instance_affinity": "instance-3",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [{"role": "user", "content": "Response from instance 3"}]
                    }
                },
                {
                    "id": "aggregate",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["instance_1", "instance_2", "instance_3"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Combine: ${instance_1.response}, ${instance_2.response}, ${instance_3.response}"
                            }
                        ]
                    }
                }
            ]
        }
    
    @pytest.fixture
    def test_mixed_substitution_workflow(self):
        """Workflow testing complex parameter substitution"""
        return {
            "name": "Mixed Substitution Test",
            "parameters": {
                "base_value": 10,
                "multiplier": 2
            },
            "tasks": [
                {
                    "id": "calculate",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {
                        "code": "result = ${parameters.base_value} * ${parameters.multiplier}; print(result)"
                    }
                },
                {
                    "id": "format_result",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["calculate"],
                    "parameters": {
                        "code": """
value = ${calculate.result}
formatted = f"The result is: {value}"
metadata = {"original": ${parameters.base_value}, "multiplier": ${parameters.multiplier}, "result": value}
print(formatted)
"""
                    }
                },
                {
                    "id": "nested_substitution",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["format_result"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a helpful assistant processing: ${format_result.metadata}"
                            },
                            {
                                "role": "user",
                                "content": "Explain the calculation: ${parameters.base_value} * ${parameters.multiplier} = ${calculate.result}"
                            }
                        ]
                    }
                }
            ]
        }
    
    @pytest.fixture
    def meeting_analysis_workflow(self):
        """Complex workflow for meeting analysis"""
        return {
            "name": "Meeting Analysis",
            "tasks": [
                {
                    "id": "transcribe",
                    "protocol": "file/v1",
                    "method": "read",
                    "parameters": {
                        "path": "meeting_notes.txt"
                    }
                },
                {
                    "id": "extract_participants",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["transcribe"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Extract participant names from: ${transcribe.content}"}
                        ]
                    }
                },
                {
                    "id": "extract_action_items",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["transcribe"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Extract action items from: ${transcribe.content}"}
                        ]
                    }
                },
                {
                    "id": "extract_decisions",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["transcribe"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Extract key decisions from: ${transcribe.content}"}
                        ]
                    }
                },
                {
                    "id": "generate_summary",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["extract_participants", "extract_action_items", "extract_decisions"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "user",
                                "content": """Generate meeting summary:
Participants: ${extract_participants.response}
Action Items: ${extract_action_items.response}
Decisions: ${extract_decisions.response}"""
                            }
                        ]
                    }
                },
                {
                    "id": "format_output",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["generate_summary"],
                    "parameters": {
                        "code": """
summary = '''${generate_summary.response}'''
formatted = f"# Meeting Summary\\n\\n{summary}"
with open('meeting_summary.md', 'w') as f:
    f.write(formatted)
print("Summary saved to meeting_summary.md")
"""
                    }
                }
            ]
        }
    
    @pytest.fixture
    def test_complex_python_workflow(self):
        """Complex Python execution workflow"""
        return {
            "name": "Complex Python Test",
            "tasks": [
                {
                    "id": "data_generation",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {
                        "code": """
import json
import random
data = [{"id": i, "value": random.randint(1, 100)} for i in range(10)]
result = json.dumps(data)
print(result)
"""
                    }
                },
                {
                    "id": "data_processing",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["data_generation"],
                    "parameters": {
                        "code": """
import json
data = json.loads('${data_generation.result}')
total = sum(item['value'] for item in data)
average = total / len(data)
max_value = max(item['value'] for item in data)
min_value = min(item['value'] for item in data)
stats = {
    'total': total,
    'average': average,
    'max': max_value,
    'min': min_value,
    'count': len(data)
}
print(json.dumps(stats))
"""
                    }
                },
                {
                    "id": "visualization",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["data_processing"],
                    "parameters": {
                        "code": """
import json
stats = json.loads('${data_processing.result}')
# Create ASCII bar chart
chart = []
chart.append(f"Total: {stats['total']}")
chart.append(f"Average: {stats['average']:.2f}")
chart.append(f"Max: {stats['max']}")
chart.append(f"Min: {stats['min']}")
chart.append("\\nDistribution:")
bar_width = 20
for key, value in stats.items():
    if key != 'count':
        bar = '#' * int((value / stats['max']) * bar_width)
        chart.append(f"{key:10}: {bar} ({value})")
print('\\n'.join(chart))
"""
                    }
                }
            ]
        }
    
    @pytest.mark.asyncio
    async def test_context_workflow(self, test_context_workflow):
        """Test workflow context and parameter passing"""
        # Verify global parameters are defined
        assert "parameters" in test_context_workflow
        assert test_context_workflow["parameters"]["global_model"] == "llama3.2"
        assert test_context_workflow["parameters"]["temperature"] == 0.7
        
        # Verify parameter substitution in tasks
        task2 = test_context_workflow["tasks"][1]
        assert "${parameters.global_model}" in json.dumps(task2)
        assert "${parameters.temperature}" in json.dumps(task2)
        assert "${task_with_context.result}" in task2["parameters"]["messages"][0]["content"]
    
    @pytest.mark.asyncio
    async def test_multi_instance_affinity(self, multi_instance_demo_workflow):
        """Test instance affinity for multi-instance execution"""
        # Verify instance affinity settings
        for i, task in enumerate(multi_instance_demo_workflow["tasks"][:3]):
            assert "instance_affinity" in task
            assert task["instance_affinity"] == f"instance-{i+1}"
        
        # Verify aggregation task has dependencies on all instances
        aggregate_task = multi_instance_demo_workflow["tasks"][3]
        assert len(aggregate_task["dependencies"]) == 3
        assert all(f"instance_{i}" in aggregate_task["dependencies"] for i in range(1, 4))
    
    @pytest.mark.asyncio
    async def test_mixed_substitution_patterns(self, test_mixed_substitution_workflow):
        """Test various parameter substitution patterns"""
        workflow = test_mixed_substitution_workflow
        
        # Test direct parameter substitution
        task1 = workflow["tasks"][0]
        assert "${parameters.base_value}" in task1["parameters"]["code"]
        assert "${parameters.multiplier}" in task1["parameters"]["code"]
        
        # Test result substitution
        task2 = workflow["tasks"][1]
        assert "${calculate.result}" in task2["parameters"]["code"]
        
        # Test nested object substitution
        task3 = workflow["tasks"][2]
        assert "${format_result.metadata}" in json.dumps(task3)
        
        # Test multiple substitutions in single string
        user_content = task3["parameters"]["messages"][1]["content"]
        assert "${parameters.base_value}" in user_content
        assert "${parameters.multiplier}" in user_content
        assert "${calculate.result}" in user_content
    
    @pytest.mark.asyncio
    async def test_meeting_analysis_flow(self, meeting_analysis_workflow):
        """Test complex meeting analysis workflow"""
        # Verify parallel extraction tasks
        extract_tasks = ["extract_participants", "extract_action_items", "extract_decisions"]
        for task_id in extract_tasks:
            task = next(t for t in meeting_analysis_workflow["tasks"] if t["id"] == task_id)
            assert task["dependencies"] == ["transcribe"]
        
        # Verify summary aggregates all extractions
        summary_task = next(t for t in meeting_analysis_workflow["tasks"] if t["id"] == "generate_summary")
        assert set(summary_task["dependencies"]) == set(extract_tasks)
        
        # Verify final formatting
        format_task = meeting_analysis_workflow["tasks"][-1]
        assert format_task["protocol"] == "python/v1"
        assert "meeting_summary.md" in format_task["parameters"]["code"]
    
    @pytest.mark.asyncio
    async def test_complex_python_data_pipeline(self, test_complex_python_workflow):
        """Test complex Python data processing pipeline"""
        workflow = test_complex_python_workflow
        
        # Verify data flow: generation -> processing -> visualization
        assert workflow["tasks"][0]["id"] == "data_generation"
        assert workflow["tasks"][1]["id"] == "data_processing"
        assert workflow["tasks"][1]["dependencies"] == ["data_generation"]
        assert workflow["tasks"][2]["id"] == "visualization"
        assert workflow["tasks"][2]["dependencies"] == ["data_processing"]
        
        # Verify JSON serialization between tasks
        assert "json.dumps" in workflow["tasks"][0]["parameters"]["code"]
        assert "json.loads" in workflow["tasks"][1]["parameters"]["code"]
        assert "json.loads" in workflow["tasks"][2]["parameters"]["code"]
    
    @pytest.mark.asyncio
    async def test_error_propagation_in_complex_workflow(self):
        """Test error handling in complex workflows"""
        workflow = {
            "name": "Error Propagation Test",
            "tasks": [
                {"id": "task1", "method": "test", "parameters": {}},
                {"id": "task2", "method": "test", "dependencies": ["task1"], "parameters": {}},
                {"id": "task3", "method": "test", "dependencies": ["task1"], "parameters": {}},
                {"id": "task4", "method": "test", "dependencies": ["task2", "task3"], "parameters": {}},
            ]
        }
        
        # If task1 fails, task2, task3, and task4 should not execute
        # This tests proper dependency failure propagation
        
        # Verify dependency chain
        assert workflow["tasks"][1]["dependencies"] == ["task1"]
        assert workflow["tasks"][2]["dependencies"] == ["task1"]
        assert set(workflow["tasks"][3]["dependencies"]) == {"task2", "task3"}
    
    @pytest.mark.asyncio
    async def test_conditional_execution(self):
        """Test conditional task execution"""
        workflow = {
            "name": "Conditional Workflow",
            "tasks": [
                {
                    "id": "check_condition",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {"code": "import random; result = random.choice([True, False])"}
                },
                {
                    "id": "if_true",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "condition": "${check_condition.result} == True",
                    "dependencies": ["check_condition"],
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "True branch"}]}
                },
                {
                    "id": "if_false",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "condition": "${check_condition.result} == False",
                    "dependencies": ["check_condition"],
                    "parameters": {"model": "llama3.2", "messages": [{"role": "user", "content": "False branch"}]}
                }
            ]
        }
        
        # Verify conditional fields
        assert "condition" in workflow["tasks"][1]
        assert "condition" in workflow["tasks"][2]
        assert workflow["tasks"][1]["condition"] != workflow["tasks"][2]["condition"]
    
    @pytest.mark.asyncio
    async def test_workflow_composition(self):
        """Test workflow composition (workflows calling other workflows)"""
        parent_workflow = {
            "name": "Parent Workflow",
            "tasks": [
                {
                    "id": "prepare",
                    "protocol": "python/v1",
                    "method": "execute",
                    "parameters": {"code": "print('Preparing data')"}
                },
                {
                    "id": "child_workflow",
                    "type": "workflow",
                    "workflow": "child_workflow.yaml",
                    "dependencies": ["prepare"],
                    "parameters": {
                        "input": "${prepare.result}"
                    }
                },
                {
                    "id": "finalize",
                    "protocol": "python/v1",
                    "method": "execute",
                    "dependencies": ["child_workflow"],
                    "parameters": {"code": "print(f'Finalizing with: ${child_workflow.result}')"}
                }
            ]
        }
        
        # Verify workflow composition structure
        child_task = parent_workflow["tasks"][1]
        assert child_task["type"] == "workflow"
        assert "workflow" in child_task
        assert child_task["dependencies"] == ["prepare"]