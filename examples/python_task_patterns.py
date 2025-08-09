#!/usr/bin/env python3
"""
Python Task Patterns with Decorators

Shows various patterns for integrating Python functions into Gleitzeit workflows
using the @gleitzeit_task decorator approach.
"""

import asyncio
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task, start_task_service


# ============================================
# Pattern 1: Data Processing Tasks
# ============================================

@gleitzeit_task(category="data", description="Load and validate CSV data")
def load_csv_data(file_path: str) -> Dict[str, Any]:
    """Load CSV and return statistics"""
    # Mock data for example
    data = {
        "sales": [100, 150, 200, 175, 225],
        "dates": ["2024-01", "2024-02", "2024-03", "2024-04", "2024-05"]
    }
    return {
        "row_count": len(data["sales"]),
        "columns": list(data.keys()),
        "data": data,
        "loaded_at": datetime.now().isoformat()
    }


@gleitzeit_task(category="data")
def calculate_statistics(data: Dict[str, Any]) -> Dict[str, float]:
    """Calculate statistical metrics"""
    values = data.get("data", {}).get("sales", [])
    return {
        "mean": np.mean(values),
        "median": np.median(values),
        "std": np.std(values),
        "min": min(values),
        "max": max(values),
        "total": sum(values)
    }


@gleitzeit_task(category="data")
def detect_anomalies(stats: Dict[str, float], data: Dict[str, Any]) -> List[int]:
    """Detect anomalies in data"""
    values = data.get("data", {}).get("sales", [])
    mean = stats["mean"]
    std = stats["std"]
    
    anomalies = []
    for i, value in enumerate(values):
        if abs(value - mean) > 2 * std:
            anomalies.append(i)
    
    return anomalies


# ============================================
# Pattern 2: API Integration Tasks
# ============================================

@gleitzeit_task(category="api", timeout=30)
async def fetch_external_data(endpoint: str, params: Dict = None) -> Dict:
    """Fetch data from external API"""
    # Mock API call
    await asyncio.sleep(0.5)
    
    return {
        "endpoint": endpoint,
        "status": "success",
        "data": {
            "results": [1, 2, 3, 4, 5],
            "timestamp": datetime.now().isoformat()
        }
    }


@gleitzeit_task(category="api")
async def aggregate_api_responses(responses: List[Dict]) -> Dict:
    """Aggregate multiple API responses"""
    all_results = []
    for response in responses:
        if response.get("status") == "success":
            all_results.extend(response.get("data", {}).get("results", []))
    
    return {
        "total_responses": len(responses),
        "successful": sum(1 for r in responses if r.get("status") == "success"),
        "aggregated_data": all_results,
        "aggregated_at": datetime.now().isoformat()
    }


# ============================================
# Pattern 3: File Processing Tasks
# ============================================

@gleitzeit_task(category="files")
def process_text_file(content: str) -> Dict[str, Any]:
    """Process text file content"""
    lines = content.split('\n')
    words = content.split()
    
    return {
        "line_count": len(lines),
        "word_count": len(words),
        "char_count": len(content),
        "unique_words": len(set(words)),
        "avg_line_length": len(content) / max(len(lines), 1)
    }


@gleitzeit_task(category="files")
def extract_metadata(file_info: Dict) -> Dict:
    """Extract and enhance file metadata"""
    return {
        "original_stats": file_info,
        "complexity_score": file_info.get("unique_words", 0) / max(file_info.get("word_count", 1), 1),
        "processing_timestamp": datetime.now().isoformat(),
        "requires_review": file_info.get("line_count", 0) > 1000
    }


# ============================================
# Pattern 4: Validation and QA Tasks
# ============================================

@gleitzeit_task(category="validation")
def validate_llm_output(llm_response: str, expected_format: Dict) -> Dict:
    """Validate LLM output against expected format"""
    issues = []
    
    # Check length constraints
    if "max_length" in expected_format:
        if len(llm_response) > expected_format["max_length"]:
            issues.append(f"Response exceeds max length of {expected_format['max_length']}")
    
    # Check required keywords
    if "required_keywords" in expected_format:
        for keyword in expected_format["required_keywords"]:
            if keyword.lower() not in llm_response.lower():
                issues.append(f"Missing required keyword: {keyword}")
    
    # Check format (JSON, list, etc.)
    if expected_format.get("format") == "json":
        try:
            json.loads(llm_response)
        except:
            issues.append("Response is not valid JSON")
    
    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "validation_timestamp": datetime.now().isoformat()
    }


@gleitzeit_task(category="validation")
def score_quality(content: str, criteria: Dict) -> float:
    """Score content quality based on criteria"""
    score = 0.0
    max_score = len(criteria)
    
    for criterion, weight in criteria.items():
        if criterion == "length":
            if len(content) >= weight:
                score += 1
        elif criterion == "keywords":
            if all(kw in content for kw in weight):
                score += 1
        # Add more criteria as needed
    
    return score / max_score if max_score > 0 else 0.0


# ============================================
# Pattern 5: Transformation Tasks
# ============================================

@gleitzeit_task(category="transform")
def format_for_presentation(raw_data: Dict, template: str = "markdown") -> str:
    """Format data for presentation"""
    if template == "markdown":
        output = "# Data Report\n\n"
        for key, value in raw_data.items():
            output += f"## {key}\n"
            if isinstance(value, list):
                for item in value:
                    output += f"- {item}\n"
            else:
                output += f"{value}\n"
            output += "\n"
        return output
    elif template == "json":
        return json.dumps(raw_data, indent=2)
    else:
        return str(raw_data)


@gleitzeit_task(category="transform")
def merge_results(results: List[Dict], merge_key: str = None) -> Dict:
    """Merge multiple results into single structure"""
    if merge_key:
        merged = {}
        for result in results:
            if merge_key in result:
                merged[result[merge_key]] = result
        return merged
    else:
        # Simple merge
        merged = {}
        for result in results:
            merged.update(result)
        return merged


# ============================================
# Example Workflows Using These Tasks
# ============================================

async def data_pipeline_example():
    """Example: Data processing pipeline with validation"""
    
    # Start task service
    await start_task_service(auto_discover=False)
    
    # Create cluster and workflow
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Data Processing Pipeline")
    
    # Step 1: Load data
    load_task = workflow.add_external_task(
        name="Load Data",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "load_csv_data",
            "args": ["sales_data.csv"]
        }
    )
    
    # Step 2: Calculate statistics
    stats_task = workflow.add_external_task(
        name="Calculate Stats",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "calculate_statistics",
            "args": ["{{Load Data.result}}"]
        },
        dependencies=["Load Data"]
    )
    
    # Step 3: Detect anomalies
    anomaly_task = workflow.add_external_task(
        name="Detect Anomalies",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "detect_anomalies",
            "args": ["{{Calculate Stats.result}}", "{{Load Data.result}}"]
        },
        dependencies=["Calculate Stats", "Load Data"]
    )
    
    # Step 4: LLM analysis of anomalies
    llm_analysis = workflow.add_text_task(
        name="Analyze Anomalies",
        prompt="""
        Analyze these statistics and anomalies:
        Stats: {{Calculate Stats.result}}
        Anomaly indices: {{Detect Anomalies.result}}
        Provide business insights.
        """,
        model="llama3",
        dependencies=["Calculate Stats", "Detect Anomalies"]
    )
    
    # Step 5: Validate LLM output
    validation = workflow.add_external_task(
        name="Validate Analysis",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "validate_llm_output",
            "args": [
                "{{Analyze Anomalies.result}}",
                {"max_length": 1000, "required_keywords": ["insight", "recommendation"]}
            ]
        },
        dependencies=["Analyze Anomalies"]
    )
    
    # Step 6: Format final report
    report = workflow.add_external_task(
        name="Format Report",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "format_for_presentation",
            "args": [
                {
                    "statistics": "{{Calculate Stats.result}}",
                    "anomalies": "{{Detect Anomalies.result}}",
                    "analysis": "{{Analyze Anomalies.result}}",
                    "validation": "{{Validate Analysis.result}}"
                },
                "markdown"
            ]
        },
        dependencies=["Calculate Stats", "Detect Anomalies", "Analyze Anomalies", "Validate Analysis"]
    )
    
    # Execute workflow
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📊 Data Pipeline Complete")
    print(result.results.get("Format Report", "No report generated"))
    
    await cluster.stop()


async def api_aggregation_example():
    """Example: Aggregate data from multiple APIs"""
    
    await start_task_service(auto_discover=False)
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("API Aggregation")
    
    # Fetch from multiple endpoints in parallel
    endpoints = [
        "https://api.example.com/data1",
        "https://api.example.com/data2",
        "https://api.example.com/data3"
    ]
    
    fetch_tasks = []
    for i, endpoint in enumerate(endpoints):
        task = workflow.add_external_task(
            name=f"Fetch API {i+1}",
            external_task_type="python_execution",
            service_name="Python Tasks",
            external_parameters={
                "function_name": "fetch_external_data",
                "args": [endpoint],
                "kwargs": {"params": {"page": 1}}
            }
        )
        fetch_tasks.append(task.name)
    
    # Aggregate all responses
    aggregate = workflow.add_external_task(
        name="Aggregate Responses",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "aggregate_api_responses",
            "args": [[f"{{{{Fetch API {i+1}.result}}}}" for i in range(len(endpoints))]]
        },
        dependencies=fetch_tasks
    )
    
    # Analyze aggregated data with LLM
    analysis = workflow.add_text_task(
        name="Analyze Data",
        prompt="Analyze this aggregated data and identify patterns: {{Aggregate Responses.result}}",
        model="mixtral",
        dependencies=["Aggregate Responses"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🌐 API Aggregation Complete")
    print(f"Analysis: {result.results['Analyze Data']}")
    
    await cluster.stop()


# ============================================
# Main
# ============================================

async def main():
    """Demonstrate Python task patterns"""
    
    print("🎯 Python Task Patterns with @gleitzeit_task")
    print("=" * 50)
    print("\nThis example shows:")
    print("1. Data processing tasks")
    print("2. API integration tasks")
    print("3. File processing tasks")
    print("4. Validation tasks")
    print("5. Transformation tasks")
    print("\nAll seamlessly integrated with LLM tasks!")
    
    print("\n" + "=" * 50)
    print("Running Data Pipeline Example...")
    print("=" * 50)
    
    await data_pipeline_example()
    
    print("\n" + "=" * 50)
    print("Running API Aggregation Example...")
    print("=" * 50)
    
    await api_aggregation_example()


if __name__ == "__main__":
    asyncio.run(main())