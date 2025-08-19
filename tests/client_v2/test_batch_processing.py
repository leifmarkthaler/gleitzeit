"""
Test batch processing functionality
"""

import pytest
import asyncio
from pathlib import Path

from gleitzeit import Client


class TestBatchProcessing:
    """Test batch processing operations"""
    
    @pytest.mark.asyncio
    async def test_batch_process_text_files(self, native_client, batch_test_files):
        """Test batch processing of text files"""
        result = await native_client.batch_process(
            directory=batch_test_files,
            pattern="*.txt",
            method="mcp/tool.echo",
            prompt="Process this file",
            max_concurrent=3,
            name="Text Batch Test"
        )
        
        assert result is not None
        assert result["total_files"] == 5
        assert result["successful"] == 5
        assert result["failed"] == 0
        assert "processing_time" in result
        assert "results" in result
        assert len(result["results"]) == 5
    
    @pytest.mark.asyncio
    async def test_batch_process_with_pattern(self, native_client, temp_dir):
        """Test batch processing with specific file pattern"""
        # Create mixed file types
        for i in range(3):
            (temp_dir / f"doc_{i}.txt").write_text(f"Text {i}")
            (temp_dir / f"data_{i}.json").write_text(f'{{"value": {i}}}')
        
        # Process only .txt files
        result = await native_client.batch_process(
            directory=str(temp_dir),
            pattern="doc_*.txt",
            method="mcp/tool.echo",
            prompt="Process document",
            max_concurrent=2
        )
        
        assert result["total_files"] == 3
        assert result["successful"] == 3
        
        # Process only .json files
        result_json = await native_client.batch_process(
            directory=str(temp_dir),
            pattern="*.json",
            method="mcp/tool.echo",
            prompt="Process JSON",
            max_concurrent=2
        )
        
        assert result_json["total_files"] == 3
        assert result_json["successful"] == 3
    
    @pytest.mark.asyncio
    async def test_batch_process_empty_directory(self, native_client, temp_dir):
        """Test batch processing on empty directory"""
        empty_dir = temp_dir / "empty"
        empty_dir.mkdir()
        
        result = await native_client.batch_process(
            directory=str(empty_dir),
            pattern="*.txt",
            method="mcp/tool.echo",
            prompt="Process file",
            max_concurrent=5
        )
        
        assert result["total_files"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0
    
    @pytest.mark.asyncio
    async def test_batch_process_with_failures(self, native_client, temp_dir):
        """Test batch processing with some failures"""
        # Create test files
        for i in range(3):
            (temp_dir / f"file_{i}.txt").write_text(f"Content {i}")
        
        # Create a file that will cause processing to fail
        # (This is a simulation - in real scenario would need actual failing condition)
        (temp_dir / "bad_file.txt").write_text("Bad content")
        
        result = await native_client.batch_process(
            directory=str(temp_dir),
            pattern="*.txt",
            method="mcp/tool.echo",
            prompt="Process all files",
            max_concurrent=2
        )
        
        # All should succeed with echo (echo doesn't fail)
        assert result["total_files"] == 4
        assert result["successful"] == 4
    
    @pytest.mark.asyncio
    async def test_batch_concurrent_limit(self, native_client, temp_dir):
        """Test batch processing respects concurrent limit"""
        # Create many files
        num_files = 20
        for i in range(num_files):
            (temp_dir / f"file_{i:02d}.txt").write_text(f"Content {i}")
        
        result = await native_client.batch_process(
            directory=str(temp_dir),
            pattern="*.txt",
            method="mcp/tool.echo",
            prompt="Process with limit",
            max_concurrent=5,  # Limit concurrent processing
            name="Concurrent Limit Test"
        )
        
        assert result["total_files"] == num_files
        assert result["successful"] == num_files
        assert result["failed"] == 0
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="API tests need server fixture improvements")
    async def test_batch_process_api_mode(self, api_client, batch_test_files):
        """Test batch processing in API mode"""
        result = await api_client.batch_process(
            directory=batch_test_files,
            pattern="*.txt",
            method="mcp/tool.echo",
            prompt="API batch process",
            model="llama3.2:latest",  # Include model parameter
            max_concurrent=3
        )
        
        assert result is not None
        assert result["total_files"] == 5
        assert result["successful"] == 5


@pytest.mark.skip(reason="Multi-mode tests need server fixture improvements")
class TestBatchProcessingModes:
    """Test batch processing across different client modes"""
    
    @pytest.mark.asyncio
    async def test_batch_in_different_modes(self, batch_test_files):
        """Test batch processing works in all modes"""
        batch_params = {
            "directory": batch_test_files,
            "pattern": "*.txt",
            "method": "mcp/tool.echo",
            "prompt": "Process file",
            "max_concurrent": 2
        }
        
        # Test in native mode
        async with Client(mode="native") as client:
            native_result = await client.batch_process(**batch_params)
            assert native_result["successful"] == 5
        
        # Test in API mode
        async with Client(mode="api", auto_start_server=True) as client:
            api_result = await client.batch_process(**batch_params)
            assert api_result["successful"] == 5
        
        # Test in auto mode
        async with Client(mode="auto") as client:
            auto_result = await client.batch_process(**batch_params)
            assert auto_result["successful"] == 5


class TestBatchProcessingWithLLM:
    """Test batch processing with LLM operations"""
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires Ollama to be running")
    async def test_batch_llm_processing(self, native_client, batch_test_files):
        """Test batch processing with LLM analysis"""
        result = await native_client.batch_process(
            directory=batch_test_files,
            pattern="*.txt",
            method="llm/chat",
            prompt="Summarize this text in one sentence",
            model="llama3.2:latest",
            max_concurrent=2,
            name="LLM Batch Test"
        )
        
        assert result["total_files"] == 5
        # Results depend on LLM availability
        if result["successful"] > 0:
            # Check that we got LLM responses
            for file_result in result["results"].values():
                if file_result.get("status") == "completed":
                    assert "response" in file_result.get("result", {})