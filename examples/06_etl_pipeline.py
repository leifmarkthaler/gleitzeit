#!/usr/bin/env python3
"""
ETL Pipeline Example - Extract, Transform, Load

This example demonstrates a complete ETL pipeline using Gleitzeit
with proper dependency management between stages.
"""

import asyncio
from gleitzeit.client import GleitzeitClient


async def main():
    """ETL pipeline example"""

    async with GleitzeitClient('http://localhost:8000') as client:
        print("✓ Connected to Gleitzeit API")

        # Define ETL workflow
        workflow = {
            'name': 'ETL Pipeline',
            'tasks': [
                # EXTRACT: Fetch raw data
                {
                    'id': 'extract',
                    'type': 'python',
                    'params': {
                        'code': '''
import json

# Simulate data extraction from source
print("Extracting data from source...")
data = [
    {"id": 1, "name": "Alice", "value": 100},
    {"id": 2, "name": "Bob", "value": 200},
    {"id": 3, "name": "Charlie", "value": 300},
    {"id": 4, "name": "Diana", "value": 400},
    {"id": 5, "name": "Eve", "value": 500}
]

result = {
    "records": data,
    "count": len(data),
    "source": "database",
    "extracted_at": "2025-11-04T12:00:00Z"
}
print(f"✓ Extracted {len(data)} records")
'''
                    }
                },
                # TRANSFORM: Process and clean data
                {
                    'id': 'transform',
                    'type': 'python',
                    'depends_on': ['extract'],
                    'params': {
                        'code': '''
# Get extracted data
extract_result = inputs.get("extract", {})
records = extract_result.get("records", [])

print(f"Transforming {len(records)} records...")

# Transform: uppercase names, double values, add calculated fields
transformed = []
for record in records:
    transformed.append({
        "id": record["id"],
        "name": record["name"].upper(),
        "value": record["value"] * 2,
        "value_squared": record["value"] ** 2,
        "category": "HIGH" if record["value"] > 250 else "LOW"
    })

result = {
    "transformed": transformed,
    "count": len(transformed),
    "transformed_at": "2025-11-04T12:01:00Z"
}
print(f"✓ Transformed {len(transformed)} records")
'''
                    }
                },
                # VALIDATE: Check data quality
                {
                    'id': 'validate',
                    'type': 'python',
                    'depends_on': ['transform'],
                    'params': {
                        'code': '''
# Get transformed data
transform_result = inputs.get("transform", {})
data = transform_result.get("transformed", [])

print(f"Validating {len(data)} records...")

# Validate: check for required fields and data integrity
errors = []
valid_count = 0

for record in data:
    # Check required fields
    if not all(k in record for k in ["id", "name", "value"]):
        errors.append(f"Record {record.get('id')} missing required fields")
        continue

    # Check value is positive
    if record["value"] <= 0:
        errors.append(f"Record {record['id']}: invalid value {record['value']}")
        continue

    valid_count += 1

result = {
    "valid_count": valid_count,
    "error_count": len(errors),
    "errors": errors,
    "data_quality": "PASS" if len(errors) == 0 else "FAIL"
}
print(f"✓ Validation complete: {valid_count} valid, {len(errors)} errors")
'''
                    }
                },
                # LOAD: Save to destination
                {
                    'id': 'load',
                    'type': 'python',
                    'depends_on': ['transform', 'validate'],
                    'params': {
                        'code': '''
# Get transformed data and validation results
transform_result = inputs.get("transform", {})
validate_result = inputs.get("validate", {})

data = transform_result.get("transformed", [])
data_quality = validate_result.get("data_quality")

# Only load if validation passed
if data_quality == "PASS":
    print(f"Loading {len(data)} records to destination...")

    # Simulate loading to database/data warehouse
    loaded_ids = []
    for record in data:
        # Simulate database insert
        loaded_ids.append(record["id"])
        print(f"  Loaded record {record['id']}: {record['name']} = {record['value']}")

    result = {
        "loaded_count": len(loaded_ids),
        "loaded_ids": loaded_ids,
        "status": "success",
        "destination": "data_warehouse"
    }
    print(f"✓ Successfully loaded {len(loaded_ids)} records")
else:
    error_count = validate_result.get("error_count", 0)
    result = {
        "loaded_count": 0,
        "status": "failed",
        "reason": f"Validation failed with {error_count} errors"
    }
    print(f"✗ Load cancelled due to validation errors")
'''
                    }
                }
            ]
        }

        # Submit ETL pipeline
        response = await client.submit_workflow(workflow)
        print(f"✓ Submitted ETL pipeline: {response.workflow_id}")

        # Wait for completion
        print("\n⏳ Running ETL pipeline...")
        status = await client.wait_for_workflow(response.workflow_id, timeout=120)

        print(f"\n✓ ETL Pipeline completed: {status.status}")
        print(f"\n📊 Pipeline Results:")
        print(f"   Workflow ID: {response.workflow_id}")
        print(f"   Status: {status.status}")

        # Get load task result
        tasks = await client.get_workflow_tasks(response.workflow_id)
        load_task = next((t for t in tasks if 'load' in str(t)), None)
        if load_task:
            task_id = load_task.get('task_id') if isinstance(load_task, dict) else load_task.task_id
            result = await client.get_task_result(task_id, response.workflow_id)
            print(f"\n📥 Load Results:")
            print(f"   Loaded: {result.get('loaded_count', 0)} records")
            print(f"   Status: {result.get('status')}")


if __name__ == "__main__":
    print("=" * 60)
    print("ETL Pipeline Example")
    print("=" * 60)
    asyncio.run(main())
