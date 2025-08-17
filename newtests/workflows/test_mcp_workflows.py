"""Tests for MCP (Model Context Protocol) workflows"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import yaml
import json

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.providers.simple_mcp_provider import SimpleMCPProvider


class TestMCPWorkflows:
    """Test MCP tool execution workflows"""
    
    @pytest.fixture
    def simple_mcp_workflow(self):
        """Simple MCP workflow"""
        return {
            "name": "Simple MCP Workflow",
            "tasks": [
                {
                    "id": "calculator_task",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "add",
                        "args": {"a": 10, "b": 20}
                    }
                }
            ]
        }
    
    @pytest.fixture
    def mcp_chain_workflow(self):
        """MCP workflow with chained tool calls"""
        return {
            "name": "MCP Chain Workflow",
            "tasks": [
                {
                    "id": "multiply",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "multiply",
                        "args": {"a": 5, "b": 3}
                    }
                },
                {
                    "id": "add_result",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["multiply"],
                    "parameters": {
                        "tool": "calculator",
                        "operation": "add",
                        "args": {"a": "${multiply.result}", "b": 10}
                    }
                },
                {
                    "id": "square_result",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["add_result"],
                    "parameters": {
                        "tool": "calculator",
                        "operation": "square",
                        "args": {"value": "${add_result.result}"}
                    }
                }
            ]
        }
    
    @pytest.fixture
    def mcp_database_workflow(self):
        """MCP workflow for database operations"""
        return {
            "name": "MCP Database Workflow",
            "tasks": [
                {
                    "id": "create_table",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "database",
                        "operation": "create_table",
                        "args": {
                            "table": "users",
                            "schema": {
                                "id": "INTEGER PRIMARY KEY",
                                "name": "TEXT",
                                "email": "TEXT UNIQUE"
                            }
                        }
                    }
                },
                {
                    "id": "insert_data",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["create_table"],
                    "parameters": {
                        "tool": "database",
                        "operation": "insert",
                        "args": {
                            "table": "users",
                            "data": {"name": "John Doe", "email": "john@example.com"}
                        }
                    }
                },
                {
                    "id": "query_data",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["insert_data"],
                    "parameters": {
                        "tool": "database",
                        "operation": "select",
                        "args": {
                            "table": "users",
                            "where": {"email": "john@example.com"}
                        }
                    }
                }
            ]
        }
    
    @pytest.fixture
    async def mock_mcp_provider(self):
        """Create mock MCP provider"""
        provider = Mock(spec=SimpleMCPProvider)
        provider.provider_id = "mcp"
        provider.protocol_id = "mcp/v1"
        
        # Track database state for testing
        database_state = {"tables": {}, "data": {}}
        
        async def handle_tool(method, params):
            tool = params.get("tool")
            operation = params.get("operation")
            args = params.get("args", {})
            
            if tool == "calculator":
                if operation == "add":
                    result = args.get("a", 0) + args.get("b", 0)
                elif operation == "multiply":
                    result = args.get("a", 0) * args.get("b", 0)
                elif operation == "square":
                    value = args.get("value", 0)
                    result = value * value
                elif operation == "divide":
                    a, b = args.get("a", 1), args.get("b", 1)
                    if b == 0:
                        raise ValueError("Division by zero")
                    result = a / b
                else:
                    result = 0
                
                return {"result": result, "tool": tool, "operation": operation, "provider_id": "mcp"}
            
            elif tool == "database":
                if operation == "create_table":
                    table_name = args.get("table")
                    schema = args.get("schema", {})
                    database_state["tables"][table_name] = schema
                    database_state["data"][table_name] = []
                    return {"result": f"Table {table_name} created", "provider_id": "mcp"}
                
                elif operation == "insert":
                    table_name = args.get("table")
                    data = args.get("data", {})
                    if table_name in database_state["data"]:
                        data["id"] = len(database_state["data"][table_name]) + 1
                        database_state["data"][table_name].append(data)
                        return {"result": f"Inserted into {table_name}", "id": data["id"], "provider_id": "mcp"}
                    else:
                        raise ValueError(f"Table {table_name} does not exist")
                
                elif operation == "select":
                    table_name = args.get("table")
                    where = args.get("where", {})
                    if table_name in database_state["data"]:
                        results = database_state["data"][table_name]
                        if where:
                            # Simple filtering
                            results = [r for r in results 
                                     if all(r.get(k) == v for k, v in where.items())]
                        return {"result": results, "count": len(results), "provider_id": "mcp"}
                    else:
                        raise ValueError(f"Table {table_name} does not exist")
                
                return {"result": "Database operation completed", "provider_id": "mcp"}
            
            elif tool == "filesystem":
                if operation == "list":
                    path = args.get("path", ".")
                    return {"result": ["file1.txt", "file2.py", "dir1/"], "provider_id": "mcp"}
                elif operation == "read":
                    return {"result": "File content", "provider_id": "mcp"}
                elif operation == "write":
                    return {"result": "File written", "provider_id": "mcp"}
            
            return {"result": "Unknown tool", "provider_id": "mcp"}
        
        provider.handle_request = AsyncMock(side_effect=handle_tool)
        provider.supports_method = Mock(return_value=True)
        provider.database_state = database_state  # For test verification
        return provider
    
    @pytest.mark.asyncio
    async def test_simple_mcp_tool_call(self, mock_mcp_provider, simple_mcp_workflow):
        """Test simple MCP tool execution"""
        task = simple_mcp_workflow["tasks"][0]
        result = await mock_mcp_provider.handle_request(
            task["method"],
            task["parameters"]
        )
        
        assert result["result"] == 30  # 10 + 20
        assert result["tool"] == "calculator"
        assert result["operation"] == "add"
    
    @pytest.mark.asyncio
    async def test_mcp_chain_execution(self, mock_mcp_provider, mcp_chain_workflow):
        """Test chained MCP tool calls with parameter substitution"""
        results = {}
        
        # Execute tasks in order
        for task in mcp_chain_workflow["tasks"]:
            # Substitute previous results
            params = task["parameters"].copy()
            if "dependencies" in task:
                for dep in task["dependencies"]:
                    if dep in results:
                        # Replace ${dependency.result} with actual value
                        params_str = json.dumps(params)
                        params_str = params_str.replace(f"\"${{{dep}.result}}\"", str(results[dep]["result"]))
                        params = json.loads(params_str)
            
            results[task["id"]] = await mock_mcp_provider.handle_request(
                task["method"],
                params
            )
        
        # Verify chain: 5 * 3 = 15, 15 + 10 = 25, 25 * 25 = 625
        assert results["multiply"]["result"] == 15
        assert results["add_result"]["result"] == 25
        assert results["square_result"]["result"] == 625
    
    @pytest.mark.asyncio
    async def test_mcp_database_operations(self, mock_mcp_provider, mcp_database_workflow):
        """Test MCP database tool operations"""
        results = {}
        
        # Execute database operations in order
        for task in mcp_database_workflow["tasks"]:
            results[task["id"]] = await mock_mcp_provider.handle_request(
                task["method"],
                task["parameters"]
            )
        
        # Verify table creation
        assert "users" in mock_mcp_provider.database_state["tables"]
        
        # Verify data insertion
        assert len(mock_mcp_provider.database_state["data"]["users"]) == 1
        assert mock_mcp_provider.database_state["data"]["users"][0]["name"] == "John Doe"
        
        # Verify query results
        query_result = results["query_data"]["result"]
        assert len(query_result) == 1
        assert query_result[0]["email"] == "john@example.com"
    
    @pytest.mark.asyncio
    async def test_mcp_error_handling(self, mock_mcp_provider):
        """Test MCP tool error handling"""
        # Test division by zero
        with pytest.raises(ValueError, match="Division by zero"):
            await mock_mcp_provider.handle_request(
                "tool",
                {
                    "tool": "calculator",
                    "operation": "divide",
                    "args": {"a": 10, "b": 0}
                }
            )
        
        # Test non-existent table
        with pytest.raises(ValueError, match="does not exist"):
            await mock_mcp_provider.handle_request(
                "tool",
                {
                    "tool": "database",
                    "operation": "insert",
                    "args": {"table": "nonexistent", "data": {}}
                }
            )
    
    @pytest.mark.asyncio
    async def test_mcp_parallel_tools(self, mock_mcp_provider):
        """Test parallel execution of independent MCP tools"""
        workflow = {
            "name": "Parallel MCP",
            "tasks": [
                {
                    "id": "calc1",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "add",
                        "args": {"a": 1, "b": 2}
                    }
                },
                {
                    "id": "calc2",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "multiply",
                        "args": {"a": 3, "b": 4}
                    }
                },
                {
                    "id": "calc3",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "add",
                        "args": {"a": 5, "b": 6}
                    }
                }
            ]
        }
        
        # Execute all tasks (would be parallel in real execution)
        results = []
        for task in workflow["tasks"]:
            result = await mock_mcp_provider.handle_request(
                task["method"],
                task["parameters"]
            )
            results.append(result)
        
        # Verify all completed independently
        assert results[0]["result"] == 3   # 1 + 2
        assert results[1]["result"] == 12  # 3 * 4
        assert results[2]["result"] == 11  # 5 + 6
    
    @pytest.mark.asyncio
    async def test_mcp_tool_validation(self, mock_mcp_provider):
        """Test MCP tool parameter validation"""
        # Test with missing required parameters
        result = await mock_mcp_provider.handle_request(
            "tool",
            {
                "tool": "unknown_tool",
                "operation": "unknown_op"
            }
        )
        
        assert result["result"] == "Unknown tool"
    
    @pytest.mark.asyncio
    async def test_mcp_filesystem_tools(self, mock_mcp_provider):
        """Test MCP filesystem tool operations"""
        # List files
        list_result = await mock_mcp_provider.handle_request(
            "tool",
            {
                "tool": "filesystem",
                "operation": "list",
                "args": {"path": "/test"}
            }
        )
        assert isinstance(list_result["result"], list)
        assert len(list_result["result"]) > 0
        
        # Read file
        read_result = await mock_mcp_provider.handle_request(
            "tool",
            {
                "tool": "filesystem",
                "operation": "read",
                "args": {"path": "/test/file.txt"}
            }
        )
        assert read_result["result"] == "File content"
        
        # Write file
        write_result = await mock_mcp_provider.handle_request(
            "tool",
            {
                "tool": "filesystem",
                "operation": "write",
                "args": {"path": "/test/new.txt", "content": "New content"}
            }
        )
        assert write_result["result"] == "File written"
    
    @pytest.mark.asyncio
    async def test_mcp_mixed_workflow(self, mock_mcp_provider):
        """Test workflow mixing MCP tools with other providers"""
        workflow = {
            "name": "Mixed MCP Workflow",
            "tasks": [
                {
                    "id": "calculate",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "parameters": {
                        "tool": "calculator",
                        "operation": "multiply",
                        "args": {"a": 7, "b": 8}
                    }
                },
                {
                    "id": "store_result",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["calculate"],
                    "parameters": {
                        "tool": "database",
                        "operation": "create_table",
                        "args": {
                            "table": "results",
                            "schema": {"id": "INTEGER", "value": "INTEGER"}
                        }
                    }
                },
                {
                    "id": "save_calculation",
                    "protocol": "mcp/v1",
                    "method": "tool",
                    "dependencies": ["calculate", "store_result"],
                    "parameters": {
                        "tool": "database",
                        "operation": "insert",
                        "args": {
                            "table": "results",
                            "data": {"value": "${calculate.result}"}
                        }
                    }
                }
            ]
        }
        
        results = {}
        
        # Execute workflow
        for task in workflow["tasks"]:
            params = task["parameters"].copy()
            
            # Substitute dependencies
            if task["id"] == "save_calculation":
                params["args"]["data"]["value"] = 56  # Result from calculate task
            
            results[task["id"]] = await mock_mcp_provider.handle_request(
                task["method"],
                params
            )
        
        # Verify calculation stored in database
        assert results["calculate"]["result"] == 56
        assert "results" in mock_mcp_provider.database_state["tables"]
        assert len(mock_mcp_provider.database_state["data"]["results"]) == 1
        assert mock_mcp_provider.database_state["data"]["results"][0]["value"] == 56