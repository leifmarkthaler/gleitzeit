"""Tests for batch processing workflows"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import yaml
import tempfile
import os

from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.core.batch_processor import BatchProcessor


class TestBatchWorkflows:
    """Test batch processing workflows"""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory with test files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test text files
            for i in range(3):
                Path(tmpdir, f"doc{i}.txt").write_text(f"Document {i} content")
            
            # Create test Python files
            Path(tmpdir, "script1.py").write_text("print('Hello')")
            Path(tmpdir, "script2.py").write_text("x = 10; print(x * 2)")
            
            # Create subdirectory with more files
            subdir = Path(tmpdir, "subdir")
            subdir.mkdir()
            Path(subdir, "nested.txt").write_text("Nested content")
            
            yield tmpdir
    
    @pytest.fixture
    def batch_text_workflow(self):
        """Load batch text analysis workflow"""
        return {
            "name": "Batch Text Analysis",
            "type": "batch",
            "batch": {
                "directory": "${temp_dir}",
                "pattern": "*.txt",
                "max_parallel": 3
            },
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {
                    "model": "llama3.2",
                    "messages": [
                        {"role": "user", "content": "Analyze this text: ${file.content}"}
                    ]
                }
            }
        }
    
    @pytest.fixture
    def batch_python_workflow(self):
        """Load batch Python workflow"""
        return {
            "name": "Batch Python Processing",
            "type": "batch",
            "batch": {
                "directory": "${temp_dir}",
                "pattern": "*.py",
                "max_parallel": 2
            },
            "template": {
                "protocol": "python/v1",
                "method": "execute",
                "parameters": {
                    "code": "exec(open('${file.path}').read())"
                }
            }
        }
    
    @pytest.fixture
    async def mock_ollama_provider(self):
        """Create mock Ollama provider"""
        provider = Mock()
        provider.provider_id = "ollama"
        provider.protocol_id = "llm/v1"
        
        async def analyze_text(method, params):
            content = params["messages"][0]["content"]
            return {
                "response": f"Analysis of: {content[:50]}...",
                "provider_id": "ollama"
            }
        
        provider.handle_request = AsyncMock(side_effect=analyze_text)
        return provider
    
    @pytest.fixture
    async def mock_python_provider(self):
        """Create mock Python provider"""
        provider = Mock()
        provider.provider_id = "python"
        provider.protocol_id = "python/v1"
        
        async def execute_code(method, params):
            code = params["code"]
            return {
                "result": "Executed",
                "output": f"Output from: {code[:30]}...",
                "provider_id": "python"
            }
        
        provider.handle_request = AsyncMock(side_effect=execute_code)
        return provider
    
    @pytest.fixture
    async def batch_processor(self, mock_ollama_provider, mock_python_provider):
        """Create batch processor"""
        processor = BatchProcessor()
        processor.providers = {
            "llm/v1": mock_ollama_provider,
            "python/v1": mock_python_provider
        }
        return processor
    
    @pytest.mark.asyncio
    async def test_batch_file_discovery(self, batch_processor, temp_dir):
        """Test batch processor discovers files correctly"""
        files = batch_processor.discover_files(temp_dir, "*.txt")
        
        # Should find all txt files
        txt_files = [f for f in files if f.endswith(".txt")]
        assert len(txt_files) >= 3  # doc0.txt, doc1.txt, doc2.txt
        
        # Test recursive discovery
        files_recursive = batch_processor.discover_files(temp_dir, "**/*.txt")
        assert len(files_recursive) >= 4  # Including nested.txt
    
    @pytest.mark.asyncio
    async def test_batch_text_processing(self, batch_processor, batch_text_workflow, temp_dir, mock_ollama_provider):
        """Test batch processing of text files"""
        batch_text_workflow["batch"]["directory"] = temp_dir
        
        # Process batch
        results = await batch_processor.process_batch(batch_text_workflow)
        
        # Should process all text files
        assert len(results) >= 3
        
        # Verify each file was processed
        for file_path, result in results.items():
            assert "Analysis of:" in result.get("response", "")
            assert file_path.endswith(".txt")
        
        # Verify parallel processing limit
        assert batch_processor.max_parallel <= 3
    
    @pytest.mark.asyncio
    async def test_batch_python_processing(self, batch_processor, batch_python_workflow, temp_dir, mock_python_provider):
        """Test batch processing of Python files"""
        batch_python_workflow["batch"]["directory"] = temp_dir
        
        # Process batch
        results = await batch_processor.process_batch(batch_python_workflow)
        
        # Should process all Python files
        assert len(results) >= 2  # script1.py, script2.py
        
        # Verify each file was processed
        for file_path, result in results.items():
            assert file_path.endswith(".py")
            assert "output" in result
    
    @pytest.mark.asyncio
    async def test_batch_parallel_limit(self, batch_processor, temp_dir):
        """Test batch respects parallel processing limit"""
        # Create many files
        for i in range(10):
            Path(temp_dir, f"file{i}.txt").write_text(f"Content {i}")
        
        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()
        
        async def track_concurrency(method, params):
            nonlocal concurrent_count, max_concurrent
            
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            
            await asyncio.sleep(0.1)  # Simulate work
            
            async with lock:
                concurrent_count -= 1
            
            return {"response": "done"}
        
        batch_processor.providers["llm/v1"].handle_request = track_concurrency
        
        workflow = {
            "type": "batch",
            "batch": {
                "directory": temp_dir,
                "pattern": "file*.txt",
                "max_parallel": 3
            },
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {"messages": [{"role": "user", "content": "test"}]}
            }
        }
        
        await batch_processor.process_batch(workflow)
        
        # Max concurrent should not exceed limit
        assert max_concurrent <= 3
    
    @pytest.mark.asyncio
    async def test_batch_error_handling(self, batch_processor, temp_dir):
        """Test batch handles individual file errors"""
        # Create files
        Path(temp_dir, "good.txt").write_text("Good content")
        Path(temp_dir, "bad.txt").write_text("Bad content")
        
        async def fail_on_bad(method, params):
            content = params["messages"][0]["content"]
            if "Bad content" in content:
                raise Exception("Failed to process bad file")
            return {"response": "Processed"}
        
        batch_processor.providers["llm/v1"].handle_request = fail_on_bad
        
        workflow = {
            "type": "batch",
            "batch": {"directory": temp_dir, "pattern": "*.txt"},
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {"messages": [{"role": "user", "content": "${file.content}"}]}
            }
        }
        
        results = await batch_processor.process_batch(workflow)
        
        # Good file should succeed
        good_result = results.get(str(Path(temp_dir, "good.txt")))
        assert good_result and "response" in good_result
        
        # Bad file should have error
        bad_result = results.get(str(Path(temp_dir, "bad.txt")))
        assert bad_result and ("error" in bad_result or "response" not in bad_result)
    
    @pytest.mark.asyncio
    async def test_batch_dynamic_parameters(self, batch_processor, temp_dir):
        """Test batch with dynamic parameters per file"""
        # Create files with different extensions
        Path(temp_dir, "doc.txt").write_text("Text document")
        Path(temp_dir, "script.py").write_text("print('Python')")
        Path(temp_dir, "data.json").write_text('{"key": "value"}')
        
        workflow = {
            "type": "batch",
            "batch": {"directory": temp_dir, "pattern": "*.*"},
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {
                    "messages": [
                        {"role": "user", "content": "Process ${file.name} of type ${file.extension}"}
                    ]
                }
            }
        }
        
        processed_files = []
        
        async def capture_params(method, params):
            content = params["messages"][0]["content"]
            processed_files.append(content)
            return {"response": content}
        
        batch_processor.providers["llm/v1"].handle_request = capture_params
        
        await batch_processor.process_batch(workflow)
        
        # Verify file-specific parameters were substituted
        assert any("doc.txt" in f and "txt" in f for f in processed_files)
        assert any("script.py" in f and "py" in f for f in processed_files)
        assert any("data.json" in f and "json" in f for f in processed_files)
    
    @pytest.mark.asyncio
    async def test_batch_mixed_workflow(self, batch_processor, temp_dir):
        """Test batch workflow with mixed file types and providers"""
        # Create mixed files
        Path(temp_dir, "text.txt").write_text("Analyze this")
        Path(temp_dir, "code.py").write_text("x = 10")
        
        workflow = {
            "type": "batch",
            "batch": {"directory": temp_dir, "pattern": "*.*"},
            "tasks": [
                {
                    "condition": "${file.extension == 'txt'}",
                    "template": {
                        "protocol": "llm/v1",
                        "method": "chat",
                        "parameters": {"messages": [{"role": "user", "content": "${file.content}"}]}
                    }
                },
                {
                    "condition": "${file.extension == 'py'}",
                    "template": {
                        "protocol": "python/v1",
                        "method": "execute",
                        "parameters": {"code": "${file.content}"}
                    }
                }
            ]
        }
        
        # This tests conditional processing based on file type
        # Implementation would route to different providers based on conditions
    
    @pytest.mark.asyncio
    async def test_batch_result_aggregation(self, batch_processor, temp_dir):
        """Test aggregating results from batch processing"""
        # Create files
        for i in range(3):
            Path(temp_dir, f"data{i}.txt").write_text(f"Value: {i * 10}")
        
        results_collected = []
        
        async def collect_results(method, params):
            content = params["messages"][0]["content"]
            value = int(content.split(":")[1].strip())
            results_collected.append(value)
            return {"response": f"Processed {value}", "value": value}
        
        batch_processor.providers["llm/v1"].handle_request = collect_results
        
        workflow = {
            "type": "batch",
            "batch": {"directory": temp_dir, "pattern": "data*.txt"},
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {"messages": [{"role": "user", "content": "${file.content}"}]}
            },
            "aggregate": {
                "method": "sum",
                "field": "value"
            }
        }
        
        results = await batch_processor.process_batch(workflow)
        
        # All files should be processed
        assert len(results) == 3
        
        # Results should be collected
        assert len(results_collected) == 3
        assert sum(results_collected) == 30  # 0 + 10 + 20
    
    @pytest.mark.asyncio
    async def test_batch_recursive_processing(self, batch_processor, temp_dir):
        """Test recursive directory processing"""
        # Create nested structure
        for i in range(2):
            subdir = Path(temp_dir, f"dir{i}")
            subdir.mkdir()
            Path(subdir, f"file{i}.txt").write_text(f"Content in dir{i}")
            
            subsubdir = Path(subdir, "nested")
            subsubdir.mkdir()
            Path(subsubdir, f"deep{i}.txt").write_text(f"Deep content {i}")
        
        workflow = {
            "type": "batch",
            "batch": {
                "directory": temp_dir,
                "pattern": "**/*.txt",  # Recursive pattern
                "recursive": True
            },
            "template": {
                "protocol": "llm/v1",
                "method": "chat",
                "parameters": {"messages": [{"role": "user", "content": "${file.path}"}]}
            }
        }
        
        processed_paths = []
        
        async def track_paths(method, params):
            path = params["messages"][0]["content"]
            processed_paths.append(path)
            return {"response": "done"}
        
        batch_processor.providers["llm/v1"].handle_request = track_paths
        
        await batch_processor.process_batch(workflow)
        
        # Should find all nested files
        assert len(processed_paths) >= 4  # 2 in subdirs + 2 in nested subdirs
        assert any("nested" in path for path in processed_paths)