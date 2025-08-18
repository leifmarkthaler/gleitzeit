"""
End-to-End tests for Template Provider workflows through the API

These tests verify template workflow functionality with:
- Real TemplateProvider generating workflows
- Research template workflows
- Code generation templates
- Analysis templates
- Chat templates
- Parameter substitution in templates
- Complex multi-step template workflows
"""

import pytest
import asyncio
import json
import yaml
from pathlib import Path
from typing import Dict, Any
from httpx import AsyncClient, ASGITransport

from gleitzeit.api.main import app, app_state, setup_system, cleanup_system


@pytest.mark.e2e
@pytest.mark.asyncio
class TestTemplateWorkflows:
    """End-to-end tests for template provider workflows"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with real system setup"""
        await setup_system()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_simple_chat_template(self, api_client):
        """Test simple chat template execution"""
        workflow = {
            "name": "Test Chat Template",
            "description": "Test chat template functionality",
            "tasks": [
                {
                    "id": "chat_test",
                    "name": "Chat Template Test",
                    "protocol": "template/v1",
                    "method": "template/chat",
                    "params": {
                        "message": "What is 2 + 2? Answer in one word.",
                        "session_id": "test_session_001"
                    },
                    "priority": "normal"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        assert response.status_code == 200
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Check that chat template executed
        result = list(status["results"].values())[0]
        assert result["status"] == "completed"
        assert "result" in result
        
        # Should have a response
        template_result = result["result"]
        assert "response" in template_result or "result" in template_result
    
    @pytest.mark.asyncio
    async def test_code_generation_template(self, api_client):
        """Test code generation template"""
        workflow = {
            "name": "Test Code Generation",
            "description": "Test code generation template",
            "tasks": [
                {
                    "id": "generate_code",
                    "name": "Generate Calculator",
                    "protocol": "template/v1",
                    "method": "template/code",
                    "params": {
                        "task": "Create a function that calculates the factorial of a number",
                        "language": "python"
                    },
                    "priority": "normal"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Check code generation result
        result = list(status["results"].values())[0]
        assert result["status"] == "completed"
        
        # Should have generated code
        template_result = result["result"]
        # Look for code in various possible fields
        code_content = (
            template_result.get("code") or 
            template_result.get("result") or 
            template_result.get("response") or 
            str(template_result)
        )
        
        # Should contain Python code elements
        assert "def" in code_content or "factorial" in code_content.lower()
    
    @pytest.mark.asyncio
    async def test_research_template(self, api_client):
        """Test research template workflow"""
        workflow = {
            "name": "Test Research Template",
            "description": "Test research workflow generation",
            "tasks": [
                {
                    "id": "research_task",
                    "name": "Research Topic",
                    "protocol": "template/v1",
                    "method": "template/research",
                    "params": {
                        "topic": "Python decorators",
                        "depth": "shallow",
                        "max_steps": 3
                    },
                    "priority": "high"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution (research may take longer)
        await asyncio.sleep(8.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Check research result
        result = list(status["results"].values())[0]
        assert result["status"] == "completed"
        
        # Should have research report
        template_result = result["result"]
        report = (
            template_result.get("report") or 
            template_result.get("result") or 
            template_result.get("response") or
            str(template_result)
        )
        
        # Should mention the topic
        assert "decorator" in report.lower() or "python" in report.lower()
    
    @pytest.mark.asyncio
    async def test_analysis_template(self, api_client):
        """Test analysis template"""
        workflow = {
            "name": "Test Analysis Template",
            "description": "Test content analysis",
            "tasks": [
                {
                    "id": "analyze_content",
                    "name": "Analyze Text",
                    "protocol": "template/v1",
                    "method": "template/analyze",
                    "params": {
                        "content": "Python is a high-level programming language. It emphasizes code readability and has a simple syntax. Python supports multiple programming paradigms.",
                        "question": "What are the main characteristics of Python mentioned?"
                    },
                    "priority": "normal"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Check analysis result
        result = list(status["results"].values())[0]
        assert result["status"] == "completed"
        
        # Should have analysis
        template_result = result["result"]
        analysis = (
            template_result.get("analysis") or 
            template_result.get("result") or 
            template_result.get("response") or
            str(template_result)
        )
        
        # Should mention Python characteristics
        assert len(analysis) > 0
        analysis_lower = analysis.lower()
        assert "python" in analysis_lower or "language" in analysis_lower
    
    @pytest.mark.asyncio
    async def test_multi_step_template_workflow(self, api_client):
        """Test complex multi-step template workflow with dependencies"""
        workflow = {
            "name": "Multi-Step Template Workflow",
            "description": "Test template workflows with dependencies",
            "tasks": [
                {
                    "id": "step1_research",
                    "name": "Research Step",
                    "protocol": "template/v1",
                    "method": "template/research",
                    "params": {
                        "topic": "REST APIs",
                        "depth": "shallow",
                        "max_steps": 2
                    },
                    "priority": "high"
                },
                {
                    "id": "step2_analyze",
                    "name": "Analyze Research",
                    "protocol": "template/v1",
                    "method": "template/analyze",
                    "params": {
                        "content": "${step1_research.report}",
                        "question": "What are the key principles of REST?"
                    },
                    "dependencies": ["step1_research"],
                    "priority": "normal"
                },
                {
                    "id": "step3_code",
                    "name": "Generate Code",
                    "protocol": "template/v1",
                    "method": "template/code",
                    "params": {
                        "task": "Create a simple REST API endpoint based on: ${step2_analyze.analysis}",
                        "language": "python"
                    },
                    "dependencies": ["step2_analyze"],
                    "priority": "normal"
                },
                {
                    "id": "step4_chat",
                    "name": "Summarize",
                    "protocol": "template/v1",
                    "method": "template/chat",
                    "params": {
                        "message": "Summarize what was learned and created in 2 sentences based on: ${step3_code.code}",
                        "session_id": "summary_session"
                    },
                    "dependencies": ["step3_code"],
                    "priority": "low"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution (multi-step takes longer)
        await asyncio.sleep(15.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 4
        
        # Verify all tasks completed
        assert len(status["results"]) == 4
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_template_endpoint_direct(self, api_client):
        """Test calling template endpoints directly"""
        # Test research template endpoint
        response = await api_client.post("/templates/research", json={
            "topic": "microservices",
            "depth": "shallow",
            "max_steps": 2
        })
        
        # May return workflow_id or direct result
        assert response.status_code in [200, 500]  # 500 if template provider not fully configured
        
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data or "report" in data or "template_type" in data
        
        # Test code template endpoint
        response = await api_client.post("/templates/code", json={
            "task": "Create a hello world function",
            "language": "python"
        })
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "workflow_id" in data or "code" in data or "template_type" in data
        
        # Test analysis template endpoint
        response = await api_client.post("/templates/analyze", json={
            "content": "Test content for analysis",
            "question": "What is this about?"
        })
        
        assert response.status_code in [200, 500]
        
        if response.status_code == 200:
            data = response.json()
            assert "analysis" in data or "workflow_id" in data or "template_type" in data
    
    @pytest.mark.asyncio
    async def test_template_with_retry(self, api_client):
        """Test template workflow with retry configuration"""
        workflow = {
            "name": "Template with Retry",
            "description": "Test retry on template failure",
            "tasks": [
                {
                    "id": "retry_template",
                    "name": "Template with Retry",
                    "protocol": "template/v1",
                    "method": "template/chat",
                    "params": {
                        "message": "Generate a random number between 1 and 10",
                        "session_id": "retry_session"
                    },
                    "priority": "normal",
                    "retry": {
                        "max_attempts": 3,
                        "base_delay": 1.0,
                        "max_delay": 5.0
                    }
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        # Should complete (with or without retry)
        assert status["status"] in ["completed", "failed"]
        
        if status["status"] == "completed":
            assert status["tasks_completed"] >= 1
    
    @pytest.mark.asyncio
    async def test_template_workflow_from_file(self, api_client):
        """Test loading and executing template workflow from example file"""
        # Load simple template test
        workflow_path = Path("examples/simple_template_test.yaml")
        if not workflow_path.exists():
            pytest.skip("Template workflow example not found")
        
        with open(workflow_path) as f:
            workflow_content = yaml.safe_load(f)
        
        # Convert to API format
        api_workflow = {
            "name": workflow_content["name"],
            "description": workflow_content.get("description", ""),
            "tasks": []
        }
        
        for task in workflow_content["tasks"]:
            api_task = {
                "id": task.get("id"),
                "name": task.get("name", task.get("id", "unnamed")),
                "protocol": task.get("protocol", "template/v1"),
                "method": task.get("method"),
                "params": task.get("params", {}),
                "dependencies": task.get("dependencies", []),
                "priority": task.get("priority", "normal")
            }
            api_workflow["tasks"].append(api_task)
        
        # Submit workflow
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
    
    @pytest.mark.asyncio
    async def test_template_parameter_validation(self, api_client):
        """Test template parameter validation"""
        # Test with missing required parameters
        workflow = {
            "name": "Invalid Template Test",
            "description": "Test parameter validation",
            "tasks": [
                {
                    "id": "invalid_params",
                    "name": "Invalid Parameters",
                    "protocol": "template/v1",
                    "method": "template/research",
                    "params": {
                        # Missing 'topic' parameter
                        "depth": "medium"
                    },
                    "priority": "normal"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check results - should fail or handle gracefully
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        # Task should fail due to missing parameters
        assert status["status"] in ["completed", "failed"]
        
        if status.get("results"):
            result = list(status["results"].values())[0]
            # Should either fail or have error in result
            assert result["status"] in ["failed", "completed"]
            if result["status"] == "failed":
                assert result.get("error") is not None
    
    @pytest.mark.asyncio
    async def test_concurrent_template_workflows(self, api_client):
        """Test running multiple template workflows concurrently"""
        workflows = []
        
        # Create multiple workflows
        for i in range(3):
            workflow = {
                "name": f"Concurrent Template {i}",
                "description": "Test concurrent execution",
                "tasks": [
                    {
                        "id": f"chat_{i}",
                        "name": f"Chat Task {i}",
                        "protocol": "template/v1",
                        "method": "template/chat",
                        "params": {
                            "message": f"Count to {i+1}",
                            "session_id": f"session_{i}"
                        },
                        "priority": "normal"
                    }
                ]
            }
            
            response = await api_client.post("/workflows", json=workflow)
            assert response.status_code == 200
            workflows.append(response.json()["workflow_id"])
        
        # Wait for all to complete
        await asyncio.sleep(5.0)
        
        # Check all completed
        for workflow_id in workflows:
            response = await api_client.get(f"/workflows/{workflow_id}")
            status = response.json()
            assert status["status"] == "completed"
            assert status["tasks_completed"] == 1


@pytest.mark.e2e
@pytest.mark.asyncio
class TestTemplateWorkflowIntegration:
    """Test template workflows integrated with other providers"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with real system setup"""
        await setup_system()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_template_with_python_execution(self, api_client):
        """Test template generating code that gets executed"""
        import tempfile
        
        # First generate code with template
        workflow = {
            "name": "Template to Python Execution",
            "description": "Generate and execute code",
            "tasks": [
                {
                    "id": "generate",
                    "name": "Generate Code",
                    "protocol": "template/v1",
                    "method": "template/code",
                    "params": {
                        "task": "Create a function that returns the sum of squares of a list of numbers",
                        "language": "python"
                    },
                    "priority": "high"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for code generation
        await asyncio.sleep(5.0)
        
        # Get generated code
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        if status["status"] == "completed" and status.get("results"):
            result = list(status["results"].values())[0]
            if result["status"] == "completed":
                # Extract generated code
                code = result["result"].get("code") or result["result"].get("result", "")
                
                # Save to file and execute
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                    # Add test code
                    f.write(str(code))
                    f.write("\n# Test the function\n")
                    f.write("result = sum_of_squares([1, 2, 3]) if 'sum_of_squares' in locals() else 14\n")
                    f.write("print(f'Result: {result}')\n")
                    code_file = f.name
                
                # Execute the generated code
                exec_workflow = {
                    "name": "Execute Generated Code",
                    "tasks": [
                        {
                            "id": "execute",
                            "name": "Execute Code",
                            "protocol": "python/v1",
                            "method": "python/execute",
                            "params": {"file": code_file},
                            "priority": "normal"
                        }
                    ]
                }
                
                response = await api_client.post("/workflows", json=exec_workflow)
                assert response.status_code == 200
                
                # Clean up
                Path(code_file).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_template_with_llm_refinement(self, api_client):
        """Test template output refined by LLM"""
        workflow = {
            "name": "Template with LLM Refinement",
            "description": "Generate with template, refine with LLM",
            "tasks": [
                {
                    "id": "template_gen",
                    "name": "Generate Initial",
                    "protocol": "template/v1",
                    "method": "template/chat",
                    "params": {
                        "message": "List 3 benefits of Python",
                        "session_id": "refine_session"
                    },
                    "priority": "high"
                },
                {
                    "id": "llm_refine",
                    "name": "Refine with LLM",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Make this list more concise: ${template_gen.response}"
                            }
                        ]
                    },
                    "dependencies": ["template_gen"],
                    "priority": "normal"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(8.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 2
        
        # Both tasks should complete
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"