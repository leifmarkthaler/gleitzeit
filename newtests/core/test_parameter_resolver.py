"""
Tests for ParameterResolver service
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from gleitzeit.core.parameter_resolver import ParameterResolver
from gleitzeit.core.models import Task, TaskStatus, TaskResult


class TestParameterResolver:
    """Test suite for ParameterResolver"""
    
    @pytest.fixture
    def mock_persistence(self):
        """Create mock persistence backend"""
        persistence = Mock()
        persistence.get_task_result = AsyncMock()
        return persistence
        
    @pytest.fixture
    def resolver(self, mock_persistence):
        """Create ParameterResolver instance"""
        return ParameterResolver(mock_persistence)
        
    @pytest.fixture
    def sample_task(self):
        """Create sample task for testing"""
        return Task(
            id="task-2",
            name="process-data",
            protocol="python",
            method="process",
            params={
                "input": "${task-1.result}",
                "config": {
                    "threshold": "${setup.config.threshold}",
                    "mode": "production"
                },
                "message": "Processing ${task-1.output.count} items"
            }
        )
        
    @pytest.mark.asyncio
    async def test_simple_parameter_substitution(self, resolver, mock_persistence, sample_task):
        """Test basic parameter substitution"""
        # Setup mock result - when field_path is ['result'], it should return the value
        mock_result = Mock()
        mock_result.result = {"data": "test_value"}
        mock_persistence.get_task_result.return_value = mock_result
        
        # Modify task to have simple reference
        sample_task.params = {"input": "${task-1}"}  # Reference without .result
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(sample_task)
        
        # Verify substitution
        assert resolved["input"] == {"data": "test_value"}
        mock_persistence.get_task_result.assert_called_once_with("task-1")
        
    @pytest.mark.asyncio
    async def test_nested_field_navigation(self, resolver, mock_persistence, sample_task):
        """Test navigation through nested fields"""
        # Setup mock result with nested structure
        mock_result = Mock()
        mock_result.result = {
            "output": {
                "count": 42,
                "status": "complete"
            }
        }
        mock_persistence.get_task_result.return_value = mock_result
        
        # Task with nested reference
        sample_task.params = {"count": "${task-1.output.count}"}
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(sample_task)
        
        # Verify nested field was extracted
        assert resolved["count"] == 42
        
    @pytest.mark.asyncio
    async def test_string_interpolation(self, resolver, mock_persistence, sample_task):
        """Test parameter substitution within strings"""
        # Setup mock result
        mock_result = Mock()
        mock_result.result = {"count": 10}
        mock_persistence.get_task_result.return_value = mock_result
        
        # Task with string interpolation
        sample_task.params = {"message": "Processing ${task-1.count} items"}
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(sample_task)
        
        # Verify string interpolation
        assert resolved["message"] == "Processing 10 items"
        
    @pytest.mark.asyncio
    async def test_task_name_mapping(self, resolver, mock_persistence):
        """Test resolution using task name mapping"""
        # Setup mock result
        mock_result = Mock()
        mock_result.result = "mapped_value"
        mock_persistence.get_task_result.return_value = mock_result
        
        # Create task with name reference
        task = Task(
            id="task-2",
            name="consumer",
            protocol="python",
            method="consume",
            params={"data": "${producer.result}"}
        )
        
        # Set task name mapping
        name_mapping = {"producer": "task-1"}
        
        # Resolve with mapping
        resolved = await resolver.resolve_parameters(task, name_mapping)
        
        # Verify name was resolved to ID
        assert resolved["data"] == "mapped_value"
        mock_persistence.get_task_result.assert_called_once_with("task-1")
        
    @pytest.mark.asyncio
    async def test_missing_reference(self, resolver, mock_persistence, sample_task):
        """Test handling of missing task references"""
        # Setup mock to return None (task not found)
        mock_persistence.get_task_result.return_value = None
        
        # Task with reference to missing task
        sample_task.params = {"input": "${missing-task.result}"}
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(sample_task)
        
        # Original reference should remain unchanged
        assert resolved["input"] == "${missing-task.result}"
        
    @pytest.mark.asyncio
    async def test_recursive_dict_substitution(self, resolver, mock_persistence):
        """Test recursive substitution through nested dictionaries"""
        # Setup multiple mock results
        mock_persistence.get_task_result.side_effect = [
            Mock(result={"value": 100}),
            Mock(result={"status": "ready"})
        ]
        
        # Task with nested dictionary references
        task = Task(
            id="task-3",
            name="aggregator",
            protocol="python",
            method="aggregate",
            params={
                "config": {
                    "threshold": "${task-1.value}",
                    "nested": {
                        "status": "${task-2.status}",
                        "static": "unchanged"
                    }
                }
            }
        )
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(task)
        
        # Verify nested substitution
        assert resolved["config"]["threshold"] == 100
        assert resolved["config"]["nested"]["status"] == "ready"
        assert resolved["config"]["nested"]["static"] == "unchanged"
        
    @pytest.mark.asyncio
    async def test_list_substitution(self, resolver, mock_persistence):
        """Test substitution in lists"""
        # Setup mock results
        mock_persistence.get_task_result.side_effect = [
            Mock(result="first"),
            Mock(result="second")
        ]
        
        # Task with list containing references
        task = Task(
            id="task-3",
            name="collector",
            protocol="python",
            method="collect",
            params={
                "items": [
                    "${task-1.result}",
                    "static",
                    "${task-2.result}"
                ]
            }
        )
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(task)
        
        # Verify list substitution
        assert resolved["items"] == ["first", "static", "second"]
        
    @pytest.mark.asyncio
    async def test_no_substitution_needed(self, resolver, mock_persistence):
        """Test parameters without references pass through unchanged"""
        # Task with no references
        task = Task(
            id="task-1",
            name="static",
            protocol="python",
            method="process",
            params={
                "value": 42,
                "config": {"mode": "test"},
                "items": [1, 2, 3]
            }
        )
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(task)
        
        # Should be unchanged
        assert resolved == task.params
        # No persistence calls should be made
        mock_persistence.get_task_result.assert_not_called()
        
    @pytest.mark.asyncio
    async def test_complex_field_path(self, resolver, mock_persistence):
        """Test complex field path navigation"""
        # Setup mock with complex nested structure
        mock_result = Mock()
        mock_result.result = {
            "level1": {
                "level2": {
                    "level3": {
                        "target": "deep_value"
                    }
                }
            }
        }
        mock_persistence.get_task_result.return_value = mock_result
        
        # Task with deep field reference
        task = Task(
            id="task-2",
            name="deep",
            protocol="python",
            method="process",
            params={"value": "${task-1.level1.level2.level3.target}"}
        )
        
        # Resolve parameters
        resolved = await resolver.resolve_parameters(task)
        
        # Verify deep navigation
        assert resolved["value"] == "deep_value"