"""
Data processing and manipulation functions

Secure functions for working with structured data, JSON, CSV, and databases.
"""

import json
import csv
import io
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union
from collections import defaultdict


# ======================
# JSON PROCESSING
# ======================

def validate_json(json_string: str) -> Dict[str, Any]:
    """
    Validate and parse JSON string
    
    Args:
        json_string: JSON string to validate
        
    Returns:
        Validation result and parsed data
    """
    try:
        data = json.loads(json_string)
        return {
            "valid": True,
            "data": data,
            "type": type(data).__name__,
            "size": len(json_string)
        }
    except json.JSONDecodeError as e:
        return {
            "valid": False,
            "error": str(e),
            "line": getattr(e, 'lineno', None),
            "column": getattr(e, 'colno', None)
        }


def json_extract_fields(data: Union[Dict, List], field_paths: List[str]) -> Dict[str, Any]:
    """
    Extract specific fields from JSON data using dot notation
    
    Args:
        data: JSON data (dict or list)
        field_paths: List of field paths (e.g., ["user.name", "user.age"])
        
    Returns:
        Extracted fields
    """
    def get_nested_field(obj: Any, path: str) -> Any:
        keys = path.split('.')
        current = obj
        
        try:
            for key in keys:
                if isinstance(current, dict):
                    current = current[key]
                elif isinstance(current, list) and key.isdigit():
                    current = current[int(key)]
                else:
                    return None
            return current
        except (KeyError, IndexError, TypeError):
            return None
    
    results = {}
    for path in field_paths:
        results[path] = get_nested_field(data, path)
    
    return results


def json_transform_keys(data: Dict[str, Any], transformation: str = "lowercase") -> Dict[str, Any]:
    """
    Transform all keys in JSON object
    
    Args:
        data: JSON object
        transformation: Type of transformation (lowercase, uppercase, snake_case)
        
    Returns:
        Transformed JSON object
    """
    def transform_key(key: str) -> str:
        if transformation == "lowercase":
            return key.lower()
        elif transformation == "uppercase":
            return key.upper()
        elif transformation == "snake_case":
            import re
            # Convert camelCase to snake_case
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', key)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        else:
            return key
    
    def transform_recursive(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {transform_key(k): transform_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [transform_recursive(item) for item in obj]
        else:
            return obj
    
    return transform_recursive(data)


# ======================
# CSV PROCESSING  
# ======================

def csv_to_records(csv_string: str, delimiter: str = ",") -> Dict[str, Any]:
    """
    Convert CSV string to list of records
    
    Args:
        csv_string: CSV data as string
        delimiter: CSV delimiter
        
    Returns:
        Parsed CSV data
    """
    try:
        reader = csv.DictReader(io.StringIO(csv_string), delimiter=delimiter)
        records = list(reader)
        
        return {
            "success": True,
            "records": records,
            "count": len(records),
            "columns": reader.fieldnames if reader.fieldnames else []
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def csv_statistics(records: List[Dict[str, Any]], column: str) -> Dict[str, Any]:
    """
    Calculate statistics for a CSV column
    
    Args:
        records: List of CSV records
        column: Column name to analyze
        
    Returns:
        Column statistics
    """
    if not records or column not in records[0]:
        return {"error": f"Column '{column}' not found"}
    
    values = [record[column] for record in records if record.get(column) is not None]
    
    if not values:
        return {"error": "No non-null values found"}
    
    # Try to convert to numbers
    numeric_values = []
    text_values = []
    
    for value in values:
        try:
            numeric_values.append(float(str(value)))
        except (ValueError, TypeError):
            text_values.append(str(value))
    
    result = {
        "column": column,
        "total_values": len(values),
        "numeric_values": len(numeric_values),
        "text_values": len(text_values)
    }
    
    if numeric_values:
        result["numeric_stats"] = {
            "min": min(numeric_values),
            "max": max(numeric_values),
            "mean": sum(numeric_values) / len(numeric_values),
            "sum": sum(numeric_values)
        }
    
    if text_values:
        from collections import Counter
        counter = Counter(text_values)
        result["text_stats"] = {
            "unique_values": len(set(text_values)),
            "most_common": counter.most_common(5)
        }
    
    return result


def csv_filter_records(records: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Filter CSV records based on criteria
    
    Args:
        records: List of CSV records
        filters: Filter criteria (e.g., {"age": ">25", "status": "active"})
        
    Returns:
        Filtered records
    """
    def matches_filter(record: Dict[str, Any], key: str, criteria: str) -> bool:
        if key not in record:
            return False
        
        value = record[key]
        
        # Handle comparison operators
        if criteria.startswith('>='):
            try:
                return float(value) >= float(criteria[2:])
            except (ValueError, TypeError):
                return False
        elif criteria.startswith('<='):
            try:
                return float(value) <= float(criteria[2:])
            except (ValueError, TypeError):
                return False
        elif criteria.startswith('>'):
            try:
                return float(value) > float(criteria[1:])
            except (ValueError, TypeError):
                return False
        elif criteria.startswith('<'):
            try:
                return float(value) < float(criteria[1:])
            except (ValueError, TypeError):
                return False
        elif criteria.startswith('!='):
            return str(value) != criteria[2:]
        else:
            # Exact match or contains
            return str(criteria).lower() in str(value).lower()
    
    filtered = []
    for record in records:
        if all(matches_filter(record, key, criteria) for key, criteria in filters.items()):
            filtered.append(record)
    
    return filtered


# ======================
# DATA AGGREGATION
# ======================

def group_by_field(records: List[Dict[str, Any]], field: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Group records by field value
    
    Args:
        records: List of records
        field: Field to group by
        
    Returns:
        Grouped records
    """
    groups = defaultdict(list)
    
    for record in records:
        group_key = str(record.get(field, "null"))
        groups[group_key].append(record)
    
    return dict(groups)


def aggregate_by_group(grouped_data: Dict[str, List[Dict[str, Any]]], 
                      field: str, operation: str = "sum") -> Dict[str, Any]:
    """
    Aggregate grouped data
    
    Args:
        grouped_data: Grouped records from group_by_field
        field: Field to aggregate
        operation: Aggregation operation (sum, count, avg, min, max)
        
    Returns:
        Aggregated results
    """
    results = {}
    
    for group_name, records in grouped_data.items():
        values = [record.get(field) for record in records if record.get(field) is not None]
        
        if operation == "count":
            results[group_name] = len(records)
        elif not values:
            results[group_name] = None
        else:
            try:
                numeric_values = [float(v) for v in values]
                
                if operation == "sum":
                    results[group_name] = sum(numeric_values)
                elif operation == "avg":
                    results[group_name] = sum(numeric_values) / len(numeric_values)
                elif operation == "min":
                    results[group_name] = min(numeric_values)
                elif operation == "max":
                    results[group_name] = max(numeric_values)
                else:
                    results[group_name] = f"Unknown operation: {operation}"
            except (ValueError, TypeError):
                results[group_name] = f"Cannot perform {operation} on non-numeric data"
    
    return results


def pivot_table(records: List[Dict[str, Any]], 
                index_field: str, 
                column_field: str, 
                value_field: str,
                aggfunc: str = "sum") -> Dict[str, Any]:
    """
    Create a pivot table from records
    
    Args:
        records: List of records
        index_field: Field for rows
        column_field: Field for columns  
        value_field: Field for values
        aggfunc: Aggregation function
        
    Returns:
        Pivot table data
    """
    # Collect unique values for index and columns
    index_values = sorted(set(str(r.get(index_field, "")) for r in records))
    column_values = sorted(set(str(r.get(column_field, "")) for r in records))
    
    # Create pivot structure
    pivot_data = {}
    
    for idx_val in index_values:
        pivot_data[idx_val] = {}
        
        for col_val in column_values:
            # Find matching records
            matching_records = [
                r for r in records 
                if str(r.get(index_field, "")) == idx_val and 
                   str(r.get(column_field, "")) == col_val
            ]
            
            if not matching_records:
                pivot_data[idx_val][col_val] = 0
                continue
            
            values = [r.get(value_field) for r in matching_records if r.get(value_field) is not None]
            
            if not values:
                pivot_data[idx_val][col_val] = 0
                continue
            
            try:
                numeric_values = [float(v) for v in values]
                
                if aggfunc == "sum":
                    pivot_data[idx_val][col_val] = sum(numeric_values)
                elif aggfunc == "count":
                    pivot_data[idx_val][col_val] = len(numeric_values)
                elif aggfunc == "avg":
                    pivot_data[idx_val][col_val] = sum(numeric_values) / len(numeric_values)
                elif aggfunc == "min":
                    pivot_data[idx_val][col_val] = min(numeric_values)
                elif aggfunc == "max":
                    pivot_data[idx_val][col_val] = max(numeric_values)
                else:
                    pivot_data[idx_val][col_val] = len(numeric_values)
            except (ValueError, TypeError):
                pivot_data[idx_val][col_val] = len(values)  # Fallback to count
    
    return {
        "pivot_table": pivot_data,
        "index_field": index_field,
        "column_field": column_field,
        "value_field": value_field,
        "aggregation": aggfunc,
        "index_values": index_values,
        "column_values": column_values
    }


# ======================
# DATA VALIDATION
# ======================

def validate_data_types(records: List[Dict[str, Any]], 
                       schema: Dict[str, str]) -> Dict[str, Any]:
    """
    Validate data types in records against schema
    
    Args:
        records: List of records to validate
        schema: Type schema (e.g., {"age": "int", "name": "str"})
        
    Returns:
        Validation results
    """
    def validate_type(value: Any, expected_type: str) -> bool:
        if value is None:
            return True  # Allow null values
        
        try:
            if expected_type == "int":
                int(value)
                return True
            elif expected_type == "float":
                float(value)
                return True
            elif expected_type == "str":
                return isinstance(value, str) or value is not None
            elif expected_type == "bool":
                return isinstance(value, bool) or str(value).lower() in ("true", "false", "1", "0")
            elif expected_type == "date":
                if isinstance(value, str):
                    datetime.fromisoformat(value.replace('Z', '+00:00'))
                return True
        except (ValueError, TypeError):
            return False
        
        return False
    
    errors = []
    valid_count = 0
    
    for i, record in enumerate(records):
        record_valid = True
        
        for field, expected_type in schema.items():
            if field in record:
                if not validate_type(record[field], expected_type):
                    errors.append({
                        "record_index": i,
                        "field": field,
                        "value": record[field],
                        "expected_type": expected_type,
                        "actual_type": type(record[field]).__name__
                    })
                    record_valid = False
        
        if record_valid:
            valid_count += 1
    
    return {
        "total_records": len(records),
        "valid_records": valid_count,
        "invalid_records": len(records) - valid_count,
        "error_count": len(errors),
        "errors": errors[:100],  # Limit errors shown
        "success_rate": valid_count / len(records) if records else 1.0
    }


# ======================
# FUNCTION REGISTRY
# ======================

DATA_FUNCTIONS = {
    # JSON processing
    "validate_json": validate_json,
    "json_extract": json_extract_fields,
    "json_transform_keys": json_transform_keys,
    
    # CSV processing
    "csv_parse": csv_to_records,
    "csv_stats": csv_statistics,
    "csv_filter": csv_filter_records,
    
    # Data aggregation
    "group_by": group_by_field,
    "aggregate": aggregate_by_group,
    "pivot": pivot_table,
    
    # Data validation
    "validate_types": validate_data_types,
}


DATA_FUNCTION_DOCS = {
    name: {
        "doc": func.__doc__.strip() if func.__doc__ else "No description available",
        "category": "data_processing"
    }
    for name, func in DATA_FUNCTIONS.items()
}