"""
Custom Template Provider Example for Gleitzeit

This example shows how to create custom template methods programmatically
by extending the TemplateProvider class.
"""

import asyncio
from typing import Dict, Any, List
from datetime import datetime
import uuid

from gleitzeit.providers.template_provider import TemplateProvider
from gleitzeit.core import Task, Workflow, Priority
from gleitzeit import GleitzeitClient


class CustomTemplateProvider(TemplateProvider):
    """Extended template provider with custom template methods"""
    
    def get_supported_methods(self) -> List[str]:
        """Add custom methods to the base template methods"""
        base_methods = super().get_supported_methods()
        custom_methods = [
            "template/data_pipeline",
            "template/api_builder", 
            "template/test_suite",
            "template/deployment"
        ]
        return base_methods + custom_methods
    
    async def handle_request(self, method: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle custom template methods"""
        
        # Handle custom methods
        if method == "template/data_pipeline":
            return await self._generate_data_pipeline_workflow(parameters)
        elif method == "template/api_builder":
            return await self._generate_api_builder_workflow(parameters)
        elif method == "template/test_suite":
            return await self._generate_test_suite_workflow(parameters)
        elif method == "template/deployment":
            return await self._generate_deployment_workflow(parameters)
        else:
            # Fall back to base template methods
            return await super().handle_request(method, parameters)
    
    async def _generate_data_pipeline_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a data pipeline workflow template
        
        Creates a workflow that:
        1. Extracts data from source
        2. Validates and cleans data
        3. Transforms data
        4. Analyzes results with LLM
        5. Generates report
        """
        source = params.get("source", "database")
        transform_type = params.get("transform_type", "aggregation")
        
        workflow_id = f"template_pipeline_{uuid.uuid4().hex[:8]}"
        tasks = []
        
        # Step 1: Extract data
        tasks.append(Task(
            id="extract_data",
            name="Extract Data",
            protocol="python/v1",
            method="python/execute",
            params={
                "code": f"""
# Extract data from {source}
import json
import random

# Simulate data extraction
data = {{
    "source": "{source}",
    "records": [
        {{"id": i, "value": random.randint(10, 100), "category": f"cat_{{i%3}}"}}
        for i in range(100)
    ],
    "timestamp": "{datetime.now().isoformat()}"
}}

print(f"Extracted {{len(data['records'])}} records from {source}")
result = json.dumps(data)
"""
            },
            priority=Priority.HIGH
        ))
        
        # Step 2: Validate and clean
        tasks.append(Task(
            id="validate_clean",
            name="Validate and Clean Data",
            protocol="python/v1",
            method="python/execute",
            dependencies=["extract_data"],
            params={
                "code": """
import json

# Parse extracted data
data = json.loads('''${extract_data.result}''')

# Validation and cleaning
cleaned_records = []
invalid_count = 0

for record in data['records']:
    if record['value'] > 0:  # Simple validation
        cleaned_records.append(record)
    else:
        invalid_count += 1

result = {
    "cleaned_records": cleaned_records,
    "original_count": len(data['records']),
    "cleaned_count": len(cleaned_records),
    "invalid_count": invalid_count
}

print(f"Validated data: {result['cleaned_count']} valid, {invalid_count} invalid")
result = json.dumps(result)
"""
            },
            priority=Priority.NORMAL
        ))
        
        # Step 3: Transform data
        tasks.append(Task(
            id="transform_data",
            name="Transform Data",
            protocol="python/v1",
            method="python/execute",
            dependencies=["validate_clean"],
            params={
                "code": f"""
import json

# Parse cleaned data
data = json.loads('''${{validate_clean.result}}''')

# Apply transformation: {transform_type}
if "{transform_type}" == "aggregation":
    # Aggregate by category
    aggregated = {{}}
    for record in data['cleaned_records']:
        cat = record['category']
        if cat not in aggregated:
            aggregated[cat] = {{'count': 0, 'sum': 0, 'values': []}}
        aggregated[cat]['count'] += 1
        aggregated[cat]['sum'] += record['value']
        aggregated[cat]['values'].append(record['value'])
    
    # Calculate averages
    for cat in aggregated:
        aggregated[cat]['average'] = aggregated[cat]['sum'] / aggregated[cat]['count']
    
    result = {{
        "transformation": "{transform_type}",
        "aggregated_data": aggregated,
        "categories": list(aggregated.keys())
    }}
else:
    # Default: pass through
    result = data

print(f"Transformation complete: {{len(result.get('categories', []))}} categories")
result = json.dumps(result)
"""
            },
            priority=Priority.NORMAL
        ))
        
        # Step 4: LLM Analysis
        tasks.append(Task(
            id="analyze_results",
            name="Analyze Results",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["transform_data"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Analyze this data pipeline result:

Transformation Result: ${{transform_data.result}}

Provide insights about:
1. Data distribution patterns
2. Key metrics and statistics
3. Potential anomalies or interesting findings
4. Recommendations for further analysis"""
                }],
                "temperature": 0.6
            },
            priority=Priority.NORMAL
        ))
        
        # Step 5: Generate report
        tasks.append(Task(
            id="generate_report",
            name="Generate Pipeline Report",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["extract_data", "validate_clean", "transform_data", "analyze_results"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Generate a comprehensive data pipeline report:

Pipeline Configuration:
- Source: {source}
- Transformation: {transform_type}

Extraction Results: ${{extract_data.result}}
Validation Results: ${{validate_clean.result}}
Transformation Results: ${{transform_data.result}}
Analysis: ${{analyze_results.response}}

Create a well-structured report with:
1. Executive Summary
2. Pipeline Execution Details
3. Data Quality Metrics
4. Transformation Results
5. Key Insights and Findings
6. Recommendations"""
                }],
                "temperature": 0.4
            },
            priority=Priority.HIGH
        ))
        
        # Create and execute workflow
        workflow = Workflow(
            id=workflow_id,
            name=f"Data Pipeline: {source} -> {transform_type}",
            description="Automated data pipeline workflow",
            tasks=tasks,
            metadata={
                "template_type": "data_pipeline",
                "source": source,
                "transform_type": transform_type
            }
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Get results
        report_result = self.execution_engine.task_results.get("generate_report")
        
        return {
            "template_type": "data_pipeline",
            "workflow_id": workflow_id,
            "source": source,
            "transform_type": transform_type,
            "status": "completed" if report_result and report_result.status == "completed" else "failed",
            "execution_time": execution_time,
            "report": report_result.result.get("response") if report_result and report_result.result else None,
            "workflow_tasks": [task.id for task in tasks],
            "success": report_result and report_result.status == "completed"
        }
    
    async def _generate_api_builder_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate an API builder workflow"""
        api_spec = params.get("specification", "RESTful CRUD API")
        framework = params.get("framework", "FastAPI")
        
        workflow_id = f"template_api_{uuid.uuid4().hex[:8]}"
        tasks = []
        
        # Design API
        tasks.append(Task(
            id="design_api",
            name="Design API",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Design a {api_spec} using {framework}.

Provide:
1. API endpoints and routes
2. Request/response schemas
3. Authentication strategy
4. Error handling approach
5. Database schema if needed"""
                }],
                "temperature": 0.3
            },
            priority=Priority.HIGH
        ))
        
        # Generate API code
        tasks.append(Task(
            id="generate_api_code",
            name="Generate API Code",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["design_api"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Based on this design: ${{design_api.response}}

Generate complete {framework} code for the API including:
- All endpoints
- Request/response models
- Validation
- Error handling
- Basic authentication

Make it production-ready."""
                }],
                "temperature": 0.2
            },
            priority=Priority.NORMAL
        ))
        
        # Generate tests
        tasks.append(Task(
            id="generate_tests",
            name="Generate API Tests",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["generate_api_code"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Generate comprehensive tests for this API:

${{generate_api_code.response}}

Include:
- Unit tests
- Integration tests
- Edge cases
- Error scenarios"""
                }],
                "temperature": 0.3
            },
            priority=Priority.NORMAL
        ))
        
        workflow = Workflow(
            id=workflow_id,
            name=f"API Builder: {api_spec}",
            tasks=tasks,
            metadata={"template_type": "api_builder"}
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        api_result = self.execution_engine.task_results.get("generate_api_code")
        
        return {
            "template_type": "api_builder",
            "workflow_id": workflow_id,
            "specification": api_spec,
            "framework": framework,
            "status": "completed" if api_result and api_result.status == "completed" else "failed",
            "execution_time": execution_time,
            "api_code": api_result.result.get("response") if api_result and api_result.result else None,
            "success": api_result and api_result.status == "completed"
        }
    
    async def _generate_test_suite_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a test suite workflow"""
        code_to_test = params.get("code", "# No code provided")
        test_framework = params.get("framework", "pytest")
        
        workflow_id = f"template_tests_{uuid.uuid4().hex[:8]}"
        tasks = []
        
        # Analyze code
        tasks.append(Task(
            id="analyze_code",
            name="Analyze Code for Testing",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Analyze this code and identify what needs to be tested:

{code_to_test}

Identify:
1. Functions/methods to test
2. Edge cases
3. Error conditions
4. Integration points"""
                }],
                "temperature": 0.4
            },
            priority=Priority.HIGH
        ))
        
        # Generate tests
        tasks.append(Task(
            id="generate_tests",
            name="Generate Test Suite",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["analyze_code"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Based on analysis: ${{analyze_code.response}}

Generate a comprehensive {test_framework} test suite for:

{code_to_test}

Include all identified test cases."""
                }],
                "temperature": 0.2
            },
            priority=Priority.NORMAL
        ))
        
        workflow = Workflow(
            id=workflow_id,
            name="Test Suite Generator",
            tasks=tasks,
            metadata={"template_type": "test_suite"}
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        test_result = self.execution_engine.task_results.get("generate_tests")
        
        return {
            "template_type": "test_suite",
            "workflow_id": workflow_id,
            "framework": test_framework,
            "status": "completed" if test_result and test_result.status == "completed" else "failed",
            "execution_time": execution_time,
            "tests": test_result.result.get("response") if test_result and test_result.result else None,
            "success": test_result and test_result.status == "completed"
        }
    
    async def _generate_deployment_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a deployment workflow"""
        app_type = params.get("app_type", "web application")
        platform = params.get("platform", "kubernetes")
        
        workflow_id = f"template_deploy_{uuid.uuid4().hex[:8]}"
        tasks = []
        
        # Generate deployment config
        tasks.append(Task(
            id="deployment_config",
            name="Generate Deployment Configuration",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Generate deployment configuration for a {app_type} on {platform}.

Include:
1. Container/deployment specs
2. Service configuration
3. Scaling policies
4. Health checks
5. Environment variables
6. Security settings"""
                }],
                "temperature": 0.3
            },
            priority=Priority.HIGH
        ))
        
        # Generate CI/CD pipeline
        tasks.append(Task(
            id="cicd_pipeline",
            name="Generate CI/CD Pipeline",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["deployment_config"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Based on deployment config: ${{deployment_config.response}}

Generate a CI/CD pipeline for {platform} including:
1. Build steps
2. Test execution
3. Container build
4. Deployment stages
5. Rollback strategy"""
                }],
                "temperature": 0.3
            },
            priority=Priority.NORMAL
        ))
        
        workflow = Workflow(
            id=workflow_id,
            name=f"Deployment: {app_type} to {platform}",
            tasks=tasks,
            metadata={"template_type": "deployment"}
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        deploy_result = self.execution_engine.task_results.get("cicd_pipeline")
        
        return {
            "template_type": "deployment",
            "workflow_id": workflow_id,
            "app_type": app_type,
            "platform": platform,
            "status": "completed" if deploy_result and deploy_result.status == "completed" else "failed",
            "execution_time": execution_time,
            "pipeline": deploy_result.result.get("response") if deploy_result and deploy_result.result else None,
            "success": deploy_result and deploy_result.status == "completed"
        }


async def main():
    """Example usage of custom template provider"""
    
    # Initialize client
    async with GleitzeitClient() as client:
        
        # First, we need to replace the default template provider with our custom one
        # This requires accessing the client's internal registry
        
        # Get the execution engine from the client
        # Note: In a real implementation, you might need to expose this via the client API
        # For now, this shows the concept
        
        print("Custom Template Provider Example")
        print("=" * 50)
        
        # Example 1: Data Pipeline Template
        print("\n1. Running Data Pipeline Template...")
        pipeline_result = await client.execute_task(
            protocol="template/v1",
            method="template/data_pipeline",
            params={
                "source": "database",
                "transform_type": "aggregation"
            }
        )
        print(f"Pipeline Status: {pipeline_result.get('status')}")
        
        # Example 2: API Builder Template  
        print("\n2. Running API Builder Template...")
        api_result = await client.execute_task(
            protocol="template/v1",
            method="template/api_builder",
            params={
                "specification": "Task Management API",
                "framework": "FastAPI"
            }
        )
        print(f"API Builder Status: {api_result.get('status')}")
        
        # Example 3: Test Suite Template
        print("\n3. Running Test Suite Template...")
        test_code = """
def add(a, b):
    return a + b

def multiply(a, b):
    return a * b

class Calculator:
    def divide(self, a, b):
        if b == 0:
            raise ValueError("Cannot divide by zero")
        return a / b
"""
        
        test_result = await client.execute_task(
            protocol="template/v1",
            method="template/test_suite",
            params={
                "code": test_code,
                "framework": "pytest"
            }
        )
        print(f"Test Suite Status: {test_result.get('status')}")
        
        # Example 4: Deployment Template
        print("\n4. Running Deployment Template...")
        deploy_result = await client.execute_task(
            protocol="template/v1",
            method="template/deployment",
            params={
                "app_type": "microservice",
                "platform": "kubernetes"
            }
        )
        print(f"Deployment Status: {deploy_result.get('status')}")
        
        print("\n" + "=" * 50)
        print("All custom templates executed successfully!")


if __name__ == "__main__":
    # Note: To actually use this custom provider, you would need to:
    # 1. Modify the client initialization to use CustomTemplateProvider
    # 2. Or create a custom client that registers the CustomTemplateProvider
    # 3. Or monkey-patch the existing template provider
    
    print("""
    Note: This example shows how to create custom template methods.
    To actually use them, you need to register the CustomTemplateProvider
    with the Gleitzeit system, either by:
    
    1. Modifying the client initialization code
    2. Creating a custom client class
    3. Using the provider registry directly
    
    See the code comments for implementation details.
    """)
    
    # Uncomment to run (requires proper integration):
    # asyncio.run(main())