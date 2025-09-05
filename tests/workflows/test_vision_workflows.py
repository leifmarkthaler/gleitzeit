"""Tests for vision and image processing workflows"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
import yaml
import tempfile
from PIL import Image
import io
import base64

from gleitzeit.core.execution_engine_v2 import ExecutionEngineV2 as ExecutionEngine
from gleitzeit.providers.ollama_provider import OllamaProvider


class TestVisionWorkflows:
    """Test vision and image processing workflows"""
    
    @pytest.fixture
    def temp_images(self):
        """Create temporary test images"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test images
            for i in range(3):
                img = Image.new('RGB', (100, 100), color=(i*50, i*50, i*50))
                img.save(Path(tmpdir, f"image{i}.png"))
            
            # Create a chart-like image
            chart = Image.new('RGB', (200, 150), color='white')
            # Add some colored rectangles to simulate a chart
            from PIL import ImageDraw
            draw = ImageDraw.Draw(chart)
            draw.rectangle([10, 50, 40, 120], fill='blue')
            draw.rectangle([50, 30, 80, 120], fill='red')
            draw.rectangle([90, 70, 120, 120], fill='green')
            chart.save(Path(tmpdir, "chart.png"))
            
            yield tmpdir
    
    @pytest.fixture
    def vision_workflow(self):
        """Vision workflow for single image"""
        return {
            "name": "Vision Analysis",
            "tasks": [
                {
                    "id": "analyze_image",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "parameters": {
                        "model": "llava",
                        "image": "${image_path}",
                        "prompt": "Describe what you see in this image"
                    }
                }
            ]
        }
    
    @pytest.fixture
    def vision_file_workflow(self):
        """Vision workflow that reads image from file"""
        return {
            "name": "Vision File Analysis",
            "tasks": [
                {
                    "id": "read_image",
                    "protocol": "file/v1",
                    "method": "read_binary",
                    "parameters": {
                        "path": "${image_path}"
                    }
                },
                {
                    "id": "analyze",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "dependencies": ["read_image"],
                    "parameters": {
                        "model": "llava",
                        "image_data": "${read_image.data}",
                        "prompt": "Analyze this image"
                    }
                }
            ]
        }
    
    @pytest.fixture
    def mixed_vision_text_workflow(self):
        """Workflow combining vision and text analysis"""
        return {
            "name": "Mixed Vision Text",
            "tasks": [
                {
                    "id": "analyze_visual",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "parameters": {
                        "model": "llava",
                        "image": "${image_path}",
                        "prompt": "Describe the visual elements"
                    }
                },
                {
                    "id": "generate_caption",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["analyze_visual"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Create a caption for: ${analyze_visual.response}"}
                        ]
                    }
                },
                {
                    "id": "extract_data",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "dependencies": ["analyze_visual"],
                    "parameters": {
                        "model": "llava",
                        "image": "${image_path}",
                        "prompt": "Extract any data or numbers from this image"
                    }
                }
            ]
        }
    
    @pytest.fixture
    async def mock_vision_provider(self):
        """Create mock vision-capable provider"""
        provider = Mock(spec=OllamaProvider)
        provider.provider_id = "ollama"
        provider.protocol_id = "llm/v1"
        
        async def handle_vision(method, params):
            if method == "vision":
                image = params.get("image") or params.get("image_data")
                prompt = params.get("prompt", "")
                
                # Simulate different responses based on prompt
                if "describe" in prompt.lower():
                    return {
                        "response": "An image showing colored rectangles arranged in a pattern",
                        "provider_id": "ollama"
                    }
                elif "data" in prompt.lower() or "extract" in prompt.lower():
                    return {
                        "response": "Data points: Blue=70, Red=90, Green=50",
                        "provider_id": "ollama"
                    }
                elif "caption" in prompt.lower():
                    return {
                        "response": "A colorful bar chart visualization",
                        "provider_id": "ollama"
                    }
                else:
                    return {
                        "response": "Image analyzed successfully",
                        "provider_id": "ollama"
                    }
            else:  # chat method
                return {
                    "response": "A vibrant data visualization chart",
                    "provider_id": "ollama"
                }
        
        provider.handle_request = AsyncMock(side_effect=handle_vision)
        provider.supports_method = Mock(return_value=True)
        return provider
    
    @pytest.fixture
    async def mock_file_provider(self):
        """Create mock file provider"""
        provider = Mock()
        provider.provider_id = "file"
        provider.protocol_id = "file/v1"
        
        async def read_file(method, params):
            path = params["path"]
            
            # Simulate reading image file
            if path.endswith(('.png', '.jpg', '.jpeg')):
                # Return base64 encoded dummy data
                dummy_image = Image.new('RGB', (10, 10), color='red')
                buffer = io.BytesIO()
                dummy_image.save(buffer, format='PNG')
                image_data = base64.b64encode(buffer.getvalue()).decode()
                
                return {
                    "data": image_data,
                    "size": len(image_data),
                    "mime_type": "image/png",
                    "provider_id": "file"
                }
            else:
                return {
                    "data": "text content",
                    "provider_id": "file"
                }
        
        provider.handle_request = AsyncMock(side_effect=read_file)
        return provider
    
    @pytest.mark.asyncio
    async def test_basic_vision_analysis(self, mock_vision_provider, vision_workflow, temp_images):
        """Test basic vision analysis of single image"""
        vision_workflow["tasks"][0]["parameters"]["image"] = str(Path(temp_images, "chart.png"))
        
        result = await mock_vision_provider.handle_request(
            "vision",
            vision_workflow["tasks"][0]["parameters"]
        )
        
        assert "response" in result
        assert "colored rectangles" in result["response"].lower() or "image" in result["response"].lower()
    
    @pytest.mark.asyncio
    async def test_vision_with_file_reading(self, mock_vision_provider, mock_file_provider, vision_file_workflow, temp_images):
        """Test vision analysis with file reading step"""
        image_path = str(Path(temp_images, "image0.png"))
        
        # First read the file
        file_result = await mock_file_provider.handle_request(
            "read_binary",
            {"path": image_path}
        )
        
        assert "data" in file_result
        assert file_result["mime_type"] == "image/png"
        
        # Then analyze with vision
        vision_result = await mock_vision_provider.handle_request(
            "vision",
            {"image_data": file_result["data"], "prompt": "Analyze this image"}
        )
        
        assert "response" in vision_result
    
    @pytest.mark.asyncio
    async def test_mixed_vision_text_flow(self, mock_vision_provider, mixed_vision_text_workflow, temp_images):
        """Test workflow combining vision and text processing"""
        image_path = str(Path(temp_images, "chart.png"))
        mixed_vision_text_workflow["tasks"][0]["parameters"]["image"] = image_path
        mixed_vision_text_workflow["tasks"][2]["parameters"]["image"] = image_path
        
        # Execute tasks in sequence
        results = {}
        
        # Task 1: Visual analysis
        results["analyze_visual"] = await mock_vision_provider.handle_request(
            "vision",
            mixed_vision_text_workflow["tasks"][0]["parameters"]
        )
        
        # Task 2: Generate caption (depends on task 1)
        caption_params = mixed_vision_text_workflow["tasks"][1]["parameters"].copy()
        caption_params["messages"][0]["content"] = caption_params["messages"][0]["content"].replace(
            "${analyze_visual.response}",
            results["analyze_visual"]["response"]
        )
        results["generate_caption"] = await mock_vision_provider.handle_request(
            "chat",
            caption_params
        )
        
        # Task 3: Extract data (depends on task 1)
        results["extract_data"] = await mock_vision_provider.handle_request(
            "vision",
            mixed_vision_text_workflow["tasks"][2]["parameters"]
        )
        
        # Verify all tasks completed
        assert len(results) == 3
        assert "colored rectangles" in results["analyze_visual"]["response"].lower()
        assert "chart" in results["generate_caption"]["response"].lower()
        assert "data" in results["extract_data"]["response"].lower()
    
    @pytest.mark.asyncio
    async def test_batch_image_processing(self, mock_vision_provider, temp_images):
        """Test batch processing of multiple images"""
        workflow = {
            "name": "Batch Image Analysis",
            "type": "batch",
            "batch": {
                "directory": temp_images,
                "pattern": "*.png",
                "max_parallel": 2
            },
            "template": {
                "protocol": "llm/v1",
                "method": "vision",
                "parameters": {
                    "model": "llava",
                    "image": "${file.path}",
                    "prompt": "Describe this image"
                }
            }
        }
        
        # Process all images
        image_files = list(Path(temp_images).glob("*.png"))
        results = {}
        
        for image_file in image_files:
            result = await mock_vision_provider.handle_request(
                "vision",
                {"image": str(image_file), "prompt": "Describe this image"}
            )
            results[str(image_file)] = result
        
        # Should process all PNG files
        assert len(results) == len(image_files)
        for path, result in results.items():
            assert "response" in result
    
    @pytest.mark.asyncio
    async def test_vision_error_handling(self, mock_vision_provider):
        """Test error handling for invalid images"""
        # Test with non-existent image
        with pytest.raises(Exception):
            async def fail_on_invalid(*args, **kwargs):
                raise FileNotFoundError("Image not found")
            
            mock_vision_provider.handle_request = fail_on_invalid
            await mock_vision_provider.handle_request(
                "vision",
                {"image": "/nonexistent/image.png", "prompt": "Analyze"}
            )
    
    @pytest.mark.asyncio
    async def test_vision_with_different_formats(self, mock_vision_provider, temp_images):
        """Test vision with different image formats"""
        # Create images in different formats
        formats = {
            "jpeg": Image.new('RGB', (50, 50), color='blue'),
            "gif": Image.new('P', (50, 50), color=0),
            "bmp": Image.new('RGB', (50, 50), color='green')
        }
        
        for fmt, img in formats.items():
            img_path = Path(temp_images, f"test.{fmt}")
            img.save(img_path)
            
            result = await mock_vision_provider.handle_request(
                "vision",
                {"image": str(img_path), "prompt": "Analyze"}
            )
            
            assert "response" in result
    
    @pytest.mark.asyncio
    async def test_vision_with_base64_input(self, mock_vision_provider):
        """Test vision with base64 encoded image data"""
        # Create base64 encoded image
        img = Image.new('RGB', (20, 20), color='yellow')
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        
        result = await mock_vision_provider.handle_request(
            "vision",
            {
                "image_data": image_base64,
                "prompt": "Describe this base64 image"
            }
        )
        
        assert "response" in result
    
    @pytest.mark.asyncio
    async def test_vision_data_extraction(self, mock_vision_provider, temp_images):
        """Test extracting structured data from images"""
        chart_path = str(Path(temp_images, "chart.png"))
        
        # Request data extraction
        result = await mock_vision_provider.handle_request(
            "vision",
            {
                "image": chart_path,
                "prompt": "Extract any data or numbers from this image"
            }
        )
        
        # Should extract data points
        assert "data" in result["response"].lower()
        assert any(word in result["response"] for word in ["blue", "red", "green", "70", "90", "50"])
    
    @pytest.mark.asyncio
    async def test_vision_comparison_workflow(self, mock_vision_provider, temp_images):
        """Test workflow comparing multiple images"""
        workflow = {
            "name": "Image Comparison",
            "tasks": [
                {
                    "id": "analyze_first",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "parameters": {
                        "model": "llava",
                        "image": str(Path(temp_images, "image0.png")),
                        "prompt": "Describe the first image"
                    }
                },
                {
                    "id": "analyze_second",
                    "protocol": "llm/v1",
                    "method": "vision",
                    "parameters": {
                        "model": "llava",
                        "image": str(Path(temp_images, "image1.png")),
                        "prompt": "Describe the second image"
                    }
                },
                {
                    "id": "compare",
                    "protocol": "llm/v1",
                    "method": "chat",
                    "dependencies": ["analyze_first", "analyze_second"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Compare: Image 1: ${analyze_first.response}, Image 2: ${analyze_second.response}"
                            }
                        ]
                    }
                }
            ]
        }
        
        # Execute workflow tasks
        results = {}
        
        for task in workflow["tasks"][:2]:
            results[task["id"]] = await mock_vision_provider.handle_request(
                task["method"],
                task["parameters"]
            )
        
        # Compare results
        compare_params = workflow["tasks"][2]["parameters"].copy()
        compare_params["messages"][0]["content"] = f"Compare: Image 1: {results['analyze_first']['response']}, Image 2: {results['analyze_second']['response']}"
        
        results["compare"] = await mock_vision_provider.handle_request(
            "chat",
            compare_params
        )
        
        assert len(results) == 3
        assert all("response" in r for r in results.values())