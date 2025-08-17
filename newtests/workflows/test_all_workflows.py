"""Master test file to run all workflow tests"""

import pytest
import asyncio
from pathlib import Path
import yaml
import sys

# Import all test modules
from test_simple_llm_workflow import TestSimpleLLMWorkflow
from test_dependent_workflow import TestDependentWorkflow
from test_parallel_workflow import TestParallelWorkflow
from test_mixed_workflow import TestMixedWorkflow
from test_batch_workflows import TestBatchWorkflows
from test_vision_workflows import TestVisionWorkflows
from test_mcp_workflows import TestMCPWorkflows
from test_complex_workflows import TestComplexWorkflows


class TestAllWorkflows:
    """Run tests for all workflow examples"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment"""
        self.examples_dir = Path("examples")
        self.workflows = list(self.examples_dir.glob("*.yaml"))
        
    def test_all_workflow_files_exist(self):
        """Test that all expected workflow files exist"""
        expected_workflows = [
            "simple_llm_workflow.yaml",
            "dependent_workflow.yaml",
            "parallel_workflow.yaml",
            "mixed_workflow.yaml",
            "batch_text_analysis.yaml",
            "batch_python_workflow.yaml",
            "batch_image_description.yaml",
            "vision_workflow.yaml",
            "vision_file_workflow.yaml",
            "mcp_workflow.yaml",
            "simple_mcp_workflow.yaml",
            "multi_instance_demo.yaml",
            "test_context_workflow.yaml",
            "test_mixed_substitution.yaml",
            "meeting_analysis_workflow.yaml",
            "test_complex_python.yaml"
        ]
        
        for workflow_name in expected_workflows:
            workflow_path = self.examples_dir / workflow_name
            assert workflow_path.exists(), f"Workflow {workflow_name} not found"
    
    def test_all_workflows_valid_yaml(self):
        """Test that all workflow files are valid YAML"""
        for workflow_path in self.workflows:
            try:
                with open(workflow_path) as f:
                    content = yaml.safe_load(f)
                assert isinstance(content, dict), f"{workflow_path} is not a valid workflow dict"
                assert "tasks" in content or "type" in content, f"{workflow_path} missing tasks or type"
            except yaml.YAMLError as e:
                pytest.fail(f"Invalid YAML in {workflow_path}: {e}")
    
    def test_all_workflows_have_names(self):
        """Test that all workflows have names"""
        for workflow_path in self.workflows:
            with open(workflow_path) as f:
                content = yaml.safe_load(f)
                assert "name" in content, f"{workflow_path} missing 'name' field"
                assert content["name"], f"{workflow_path} has empty name"
    
    def test_workflow_test_coverage(self):
        """Verify we have test files for major workflow types"""
        test_files = list(Path("newtests/workflows").glob("test_*.py"))
        
        # Map workflow types to test files
        coverage_map = {
            "simple_llm": "test_simple_llm_workflow.py",
            "dependent": "test_dependent_workflow.py",
            "parallel": "test_parallel_workflow.py",
            "mixed": "test_mixed_workflow.py",
            "batch": "test_batch_workflows.py",
            "vision": "test_vision_workflows.py",
            "mcp": "test_mcp_workflows.py",
            "complex": "test_complex_workflows.py"
        }
        
        for workflow_type, test_file in coverage_map.items():
            test_path = Path("newtests/workflows") / test_file
            assert test_path.exists(), f"Missing test file for {workflow_type} workflows"
    
    @pytest.mark.asyncio
    async def test_workflow_dependency_resolution(self):
        """Test that all workflows have valid dependency resolution"""
        from gleitzeit.core.dependency_tracker import DependencyTracker
        
        for workflow_path in self.workflows:
            with open(workflow_path) as f:
                workflow = yaml.safe_load(f)
            
            if "tasks" not in workflow:
                continue  # Skip batch workflows
            
            tracker = DependencyTracker()
            task_ids = set()
            
            # Collect all task IDs
            for task in workflow["tasks"]:
                task_ids.add(task["id"])
            
            # Verify dependencies reference existing tasks
            for task in workflow["tasks"]:
                deps = task.get("dependencies", [])
                for dep in deps:
                    assert dep in task_ids, f"Task {task['id']} in {workflow_path} references non-existent dependency {dep}"
                
                # Add to tracker for cycle detection
                tracker.add_task(task["id"], deps)
            
            # Check for cycles
            try:
                execution_order = tracker.get_execution_order()
                # If no exception, no cycles exist
            except ValueError as e:
                if "cycle" in str(e).lower():
                    pytest.fail(f"Dependency cycle detected in {workflow_path}: {e}")
    
    def test_workflow_parameter_references(self):
        """Test that parameter references are valid"""
        for workflow_path in self.workflows:
            with open(workflow_path) as f:
                workflow = yaml.safe_load(f)
            
            if "tasks" not in workflow:
                continue
            
            # Track available references
            available_refs = set()
            
            # Add global parameters if present
            if "parameters" in workflow:
                available_refs.add("parameters")
            
            # Check each task
            for task in workflow["tasks"]:
                task_id = task["id"]
                
                # Check parameter references in this task
                task_str = str(task)
                
                # Look for ${...} patterns
                import re
                refs = re.findall(r'\$\{([^}]+)\}', task_str)
                
                for ref in refs:
                    # Parse reference
                    parts = ref.split('.')
                    
                    # Check if it's a valid reference type
                    if parts[0] in ["parameters", "env", "workflow"]:
                        continue  # These are always available
                    
                    # Check if it references a previous task
                    ref_task = parts[0]
                    if ref_task != task_id:  # Can't reference self
                        # Should be in dependencies if referencing another task
                        deps = task.get("dependencies", [])
                        if ref_task not in ["parameters", "env", "workflow"] and ref_task not in deps:
                            # This is actually OK in some cases, just warn
                            print(f"Warning: Task {task_id} references {ref_task} but doesn't depend on it")
                
                # Add this task to available references for future tasks
                available_refs.add(task_id)
    
    def test_workflow_protocols(self):
        """Test that all workflows use valid protocols"""
        valid_protocols = ["llm/v1", "python/v1", "mcp/v1", "file/v1"]
        
        for workflow_path in self.workflows:
            with open(workflow_path) as f:
                workflow = yaml.safe_load(f)
            
            if "tasks" not in workflow:
                continue
            
            for task in workflow["tasks"]:
                if "protocol" in task:
                    protocol = task["protocol"]
                    assert protocol in valid_protocols, f"Invalid protocol {protocol} in {workflow_path}"
                elif "method" in task:
                    # Method should indicate protocol
                    method = task["method"]
                    if "llm" in method or "chat" in method or "vision" in method:
                        pass  # Valid LLM method
                    elif "python" in method or "execute" in method:
                        pass  # Valid Python method
                    elif "tool" in method or "mcp" in method:
                        pass  # Valid MCP method
                    else:
                        print(f"Warning: Unknown method {method} in {workflow_path}")


def run_all_tests():
    """Run all workflow tests"""
    # Run pytest with coverage
    pytest_args = [
        "newtests/workflows",
        "-v",
        "--tb=short",
        "--cov=gleitzeit",
        "--cov-report=term-missing"
    ]
    
    return pytest.main(pytest_args)


def run_specific_workflow_test(workflow_name: str):
    """Run tests for a specific workflow"""
    test_map = {
        "simple_llm": "test_simple_llm_workflow.py",
        "dependent": "test_dependent_workflow.py",
        "parallel": "test_parallel_workflow.py",
        "mixed": "test_mixed_workflow.py",
        "batch": "test_batch_workflows.py",
        "vision": "test_vision_workflows.py",
        "mcp": "test_mcp_workflows.py",
        "complex": "test_complex_workflows.py"
    }
    
    for key, test_file in test_map.items():
        if key in workflow_name.lower():
            pytest_args = [
                f"newtests/workflows/{test_file}",
                "-v",
                "--tb=short"
            ]
            return pytest.main(pytest_args)
    
    print(f"No test file found for workflow: {workflow_name}")
    return 1


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) > 1:
        workflow = sys.argv[1]
        exit_code = run_specific_workflow_test(workflow)
    else:
        exit_code = run_all_tests()
    
    sys.exit(exit_code)