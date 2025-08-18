"""
End-to-End tests for Vision workflows through the API

These tests verify vision model functionality with:
- Real Ollama LLaVa model for image analysis
- Base64 encoded images
- Image file paths
- Batch image processing
- Mixed vision and text workflows
- Parameter substitution from vision results
"""

import pytest
import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Dict, Any
from PIL import Image
import io
import yaml
from httpx import AsyncClient, ASGITransport

from gleitzeit.api.main import app, app_state, setup_system, cleanup_system


def create_test_image(width: int = 100, height: int = 100, color: str = 'red') -> str:
    """Create a simple test image and return as base64"""
    img = Image.new('RGB', (width, height), color=color)
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return base64.b64encode(img_bytes.read()).decode('utf-8')


def create_multicolor_image() -> str:
    """Create a test image with 4 colored quadrants"""
    img = Image.new('RGB', (100, 100), color='white')
    pixels = img.load()
    
    # Red quadrant (top-left)
    for x in range(50):
        for y in range(50):
            pixels[x, y] = (255, 0, 0)
    
    # Green quadrant (top-right)
    for x in range(50, 100):
        for y in range(50):
            pixels[x, y] = (0, 255, 0)
    
    # Blue quadrant (bottom-left)
    for x in range(50):
        for y in range(50, 100):
            pixels[x, y] = (0, 0, 255)
    
    # Yellow quadrant (bottom-right)
    for x in range(50, 100):
        for y in range(50, 100):
            pixels[x, y] = (255, 255, 0)
    
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return base64.b64encode(img_bytes.read()).decode('utf-8')


def create_text_image(text: str = "HELLO WORLD") -> str:
    """Create an image with text"""
    from PIL import ImageDraw, ImageFont
    
    img = Image.new('RGB', (200, 100), color='white')
    draw = ImageDraw.Draw(img)
    
    # Try to use a basic font, fall back to default if not available
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 30)
    except:
        font = ImageFont.load_default()
    
    draw.text((10, 30), text, fill='black', font=font)
    
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    return base64.b64encode(img_bytes.read()).decode('utf-8')


@pytest.mark.e2e
@pytest.mark.asyncio
class TestVisionWorkflows:
    """End-to-end tests for vision workflows"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with real system setup"""
        await setup_system()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_simple_vision_with_base64(self, api_client):
        """Test vision analysis with base64 encoded image"""
        # Create a simple red image
        image_b64 = create_test_image(color='red')
        
        workflow = {
            "name": "Test Vision Base64",
            "description": "Test vision with base64 image",
            "tasks": [
                {
                    "id": "analyze",
                    "name": "Analyze Image",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": [image_b64],
                        "messages": [
                            {
                                "role": "user",
                                "content": "What is the main color in this image? Answer with just the color name."
                            }
                        ]
                    }
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
        assert response.status_code == 200
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 1
        
        # Check that vision analysis detected red
        result = list(status["results"].values())[0]
        assert result["status"] == "completed"
        assert "result" in result
        # The response should mention red
        response_text = result["result"].get("response", "").lower()
        assert "red" in response_text or "crimson" in response_text or "scarlet" in response_text
    
    @pytest.mark.asyncio
    async def test_vision_with_image_file(self, api_client):
        """Test vision analysis with image file path"""
        # Create a temporary image file
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            img = Image.new('RGB', (100, 100), color='blue')
            img.save(tmp.name, format='PNG')
            image_path = tmp.name
        
        try:
            workflow = {
                "name": "Test Vision File",
                "description": "Test vision with image file",
                "tasks": [
                    {
                        "id": "analyze_file",
                        "name": "Analyze Image File",
                        "protocol": "llm/v1",
                        "method": "llm/vision",
                        "params": {
                            "model": "llava:latest",
                            "image_path": image_path,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": "What color is this image? Reply with just the color name."
                                }
                            ]
                        }
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
            
            # Check that vision analysis detected blue
            result = list(status["results"].values())[0]
            response_text = result["result"].get("response", "").lower()
            assert "blue" in response_text
        
        finally:
            # Clean up temp file
            Path(image_path).unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_multicolor_vision_analysis(self, api_client):
        """Test vision analysis of multicolor image"""
        # Create image with 4 colored quadrants
        image_b64 = create_multicolor_image()
        
        workflow = {
            "name": "Multicolor Vision Test",
            "description": "Test vision with multiple colors",
            "tasks": [
                {
                    "id": "analyze_colors",
                    "name": "Analyze Colors",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": [image_b64],
                        "messages": [
                            {
                                "role": "user",
                                "content": "List all the colors you see in this image. Separate them with commas."
                            }
                        ]
                    }
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
        
        # Check that vision analysis detected multiple colors
        result = list(status["results"].values())[0]
        response_text = result["result"].get("response", "").lower()
        
        # Should detect at least some of the colors
        colors_found = 0
        for color in ["red", "green", "blue", "yellow"]:
            if color in response_text:
                colors_found += 1
        
        assert colors_found >= 2  # Should detect at least 2 colors
    
    @pytest.mark.asyncio
    async def test_vision_with_text_extraction(self, api_client):
        """Test vision model extracting text from image"""
        # Create image with text
        image_b64 = create_text_image("TEST 123")
        
        workflow = {
            "name": "Vision Text Extraction",
            "description": "Test OCR capabilities",
            "tasks": [
                {
                    "id": "extract_text",
                    "name": "Extract Text",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": [image_b64],
                        "messages": [
                            {
                                "role": "user",
                                "content": "What text do you see in this image? Read any text or numbers visible."
                            }
                        ]
                    }
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
        
        # Check that vision analysis detected text
        result = list(status["results"].values())[0]
        response_text = result["result"].get("response", "").upper()
        
        # Should detect either TEST or 123
        assert "TEST" in response_text or "123" in response_text
    
    @pytest.mark.asyncio
    async def test_mixed_vision_text_workflow(self, api_client):
        """Test workflow combining vision and text analysis"""
        # Create a green image
        image_b64 = create_test_image(color='green')
        
        workflow = {
            "name": "Mixed Vision Text Workflow",
            "description": "Combine vision and text processing",
            "tasks": [
                {
                    "id": "analyze_image",
                    "name": "Analyze Image",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": [image_b64],
                        "messages": [
                            {
                                "role": "user",
                                "content": "Describe this image in one sentence."
                            }
                        ]
                    },
                    "priority": "high"
                },
                {
                    "id": "extract_info",
                    "name": "Extract Information",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "dependencies": ["analyze_image"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {
                                "role": "user",
                                "content": "From this description: '${analyze_image.response}', what is the main subject or color? Answer in 1-2 words."
                            }
                        ]
                    },
                    "priority": "normal"
                },
                {
                    "id": "generate_poem",
                    "name": "Generate Poem",
                    "protocol": "llm/v1",
                    "method": "llm/chat",
                    "dependencies": ["extract_info"],
                    "params": {
                        "model": "llama3.2:latest",
                        "messages": [
                            {
                                "role": "user",
                                "content": "Write a 2-line poem about the color: ${extract_info.response}"
                            }
                        ]
                    },
                    "priority": "low"
                }
            ]
        }
        
        # Submit workflow
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution (longer for multi-step)
        await asyncio.sleep(10.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] == 3
        
        # Verify all tasks completed
        for task_id, result in status["results"].items():
            assert result["status"] == "completed"
            assert "result" in result
    
    @pytest.mark.asyncio
    async def test_batch_vision_processing(self, api_client):
        """Test batch processing of multiple images"""
        # Create temporary directory with images
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test images
            colors = ['red', 'blue', 'green']
            for i, color in enumerate(colors):
                img = Image.new('RGB', (100, 100), color=color)
                img.save(temp_path / f"test_{color}.png", format='PNG')
            
            # Submit batch processing
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.png",
                "method": "llm/vision",
                "prompt": "What is the main color in this image? Answer with just the color name.",
                "model": "llava:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_files"] == 3
            assert "batch_id" in data
            
            # Wait for batch processing
            await asyncio.sleep(10.0)
            
            # Check that images were processed
            if data.get("successful", 0) > 0:
                assert len(data["results"]) > 0
                
                # Each result should have detected a color
                for filename, result in data["results"].items():
                    if result.get("status") == "success":
                        content = result.get("content") or result.get("response") or result.get("result", "")
                        # Should mention one of the colors
                        content_lower = str(content).lower()
                        assert any(color in content_lower for color in colors)
    
    @pytest.mark.asyncio
    async def test_vision_error_handling(self, api_client):
        """Test error handling for invalid vision requests"""
        # Test with invalid base64
        workflow = {
            "name": "Invalid Vision Test",
            "description": "Test error handling",
            "tasks": [
                {
                    "id": "invalid_image",
                    "name": "Invalid Image Test",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": ["not-valid-base64!!!"],
                        "messages": [
                            {"role": "user", "content": "Describe this image"}
                        ]
                    },
                    "priority": "normal"
                }
            ]
        }
        
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(3.0)
        
        # Check that task failed gracefully
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        # Task should fail but workflow should complete
        assert status["status"] in ["completed", "failed"]
        if status.get("results"):
            result = list(status["results"].values())[0]
            # Should either fail or handle gracefully
            assert result["status"] in ["failed", "completed"]
    
    @pytest.mark.asyncio
    async def test_vision_with_multiple_images(self, api_client):
        """Test vision analysis with multiple images in one request"""
        # Create different colored images
        red_image = create_test_image(color='red')
        blue_image = create_test_image(color='blue')
        
        workflow = {
            "name": "Multi-Image Vision",
            "tasks": [
                {
                    "id": "compare_images",
                    "protocol": "llm/v1",
                    "method": "llm/vision",
                    "params": {
                        "model": "llava:latest",
                        "images": [red_image, blue_image],
                        "messages": [
                            {
                                "role": "user",
                                "content": "Compare these two images. What colors do you see in each?"
                            }
                        ]
                    }
                }
            ]
        }
        
        response = await api_client.post("/workflows", json=workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution
        await asyncio.sleep(5.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        
        # Should mention both colors
        result = list(status["results"].values())[0]
        if result["status"] == "completed":
            response_text = result["result"].get("response", "").lower()
            # Should mention at least one of the colors
            assert "red" in response_text or "blue" in response_text
    
    @pytest.mark.asyncio
    async def test_vision_workflow_from_example_file(self, api_client):
        """Test loading and executing vision workflow from example file"""
        # Load the vision workflow example
        workflow_path = Path("examples/vision_workflow.yaml")
        if not workflow_path.exists():
            pytest.skip("Vision workflow example not found")
        
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
                "name": task.get("id", "unnamed"),
                "protocol": "llm/v1",
                "method": task.get("method", "llm/chat"),
                "params": task.get("parameters", task.get("params", {})),
                "dependencies": task.get("dependencies", []),
                "priority": str(task.get("priority", "normal"))
            }
            
            # Convert priority number to string
            if isinstance(api_task["priority"], int):
                priority_map = {0: "low", 1: "normal", 2: "high", 3: "urgent"}
                api_task["priority"] = priority_map.get(api_task["priority"], "normal")
            
            api_workflow["tasks"].append(api_task)
        
        # Submit workflow
        response = await api_client.post("/workflows", json=api_workflow)
        assert response.status_code == 200
        workflow_id = response.json()["workflow_id"]
        
        # Wait for execution (longer for complex workflow)
        await asyncio.sleep(12.0)
        
        # Check results
        response = await api_client.get(f"/workflows/{workflow_id}")
        status = response.json()
        
        assert status["status"] == "completed"
        assert status["tasks_completed"] > 0
        
        # Verify vision analysis task completed
        if "analyze-image" in status["results"]:
            vision_result = status["results"]["analyze-image"]
            assert vision_result["status"] == "completed"
            assert "result" in vision_result


@pytest.mark.e2e
@pytest.mark.asyncio
class TestVisionBatchProcessing:
    """Test batch processing with vision models"""
    
    @pytest.fixture
    async def api_client(self):
        """Create API client with real system setup"""
        await setup_system()
        
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
        
        await cleanup_system()
    
    @pytest.mark.asyncio
    async def test_batch_image_analysis(self, api_client):
        """Test batch analysis of image files"""
        # Create temp directory with various images
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create images with different characteristics
            test_images = [
                ("solid_red.png", create_test_image(color='red')),
                ("solid_blue.png", create_test_image(color='blue')),
                ("multicolor.png", create_multicolor_image()),
                ("text_image.png", create_text_image("BATCH TEST"))
            ]
            
            for filename, image_b64 in test_images:
                image_data = base64.b64decode(image_b64)
                (temp_path / filename).write_bytes(image_data)
            
            # Process batch
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.png",
                "method": "llm/vision",
                "prompt": "Describe this image briefly. What do you see?",
                "model": "llava:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_files"] == 4
            assert "batch_id" in data
            
            # Allow time for vision processing
            await asyncio.sleep(15.0)
            
            # Verify results
            if data.get("successful", 0) > 0:
                assert len(data["results"]) > 0
                
                for filename, result in data["results"].items():
                    assert filename.endswith(".png")
                    if result.get("status") == "success":
                        # Should have some content
                        content = result.get("content") or result.get("response") or result.get("result", "")
                        assert len(str(content)) > 0
    
    @pytest.mark.asyncio
    async def test_mixed_file_batch_with_vision(self, api_client):
        """Test batch processing with mixed text and image files"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create text file
            (temp_path / "document.txt").write_text("This is a text document for testing.")
            
            # Create image file
            img = Image.new('RGB', (100, 100), color='purple')
            img.save(temp_path / "image.png", format='PNG')
            
            # Process all files (should handle gracefully)
            response = await api_client.post("/batch", json={
                "directory": str(temp_path),
                "pattern": "*.*",
                "method": "llm/chat",  # Use chat for mixed content
                "prompt": "Describe or summarize this content.",
                "model": "llama3.2:latest"
            })
            
            assert response.status_code == 200
            data = response.json()
            
            assert data["total_files"] == 2
            
            # Wait for processing
            await asyncio.sleep(8.0)
            
            # Should process at least the text file
            if data.get("successful", 0) > 0:
                assert "document.txt" in str(data["results"])