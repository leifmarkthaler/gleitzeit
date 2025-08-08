#!/usr/bin/env python3
"""
Vision Demo - Current API
Shows vision task capabilities (requires Ollama + llava model)
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster, Task, TaskType, TaskParameters, Workflow


async def simple_vision_analysis():
    """Simple vision analysis example"""
    
    print("👁️ Simple Vision Analysis")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Note: This requires an actual image file and Ollama with llava model
        print("📋 Note: This demo requires:")
        print("   1. Ollama installed: curl -fsSL https://ollama.ai/install.sh | sh")
        print("   2. Llava model: ollama pull llava")
        print("   3. An image file (e.g., test_image.jpg)")
        print()
        
        # Create vision task
        vision_task = Task(
            name="Analyze Image",
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                image_path="test_image.jpg",  # Replace with actual image
                prompt="Describe what you see in this image in detail",
                model_name="llava"
            )
        )
        
        workflow = Workflow(
            name="Simple Vision Analysis",
            tasks=[vision_task]
        )
        
        print("🚀 Analyzing image...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Wait for completion
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(2)  # Vision tasks take longer
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Vision analysis completed:")
            print(f"👁️ Description: {results.get(vision_task.id, 'No result')}")
        else:
            error = status.get("error", "Unknown error")
            print(f"❌ Vision analysis failed: {error}")
            if "No such file" in str(error):
                print("   💡 Create a test image file or update the image_path")
            elif "llava" in str(error).lower():
                print("   💡 Install llava model: ollama pull llava")
    
    finally:
        await cluster.stop()


async def multi_image_workflow():
    """Analyze multiple aspects of an image"""
    
    print("\n🖼️ Multi-Image Analysis Workflow")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Multiple analysis tasks on same image
        describe_task = Task(
            id="describe",
            name="Describe Image",
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                image_path="test_image.jpg",
                prompt="Describe what you see in this image",
                model_name="llava"
            )
        )
        
        count_objects_task = Task(
            id="count",
            name="Count Objects", 
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                image_path="test_image.jpg",
                prompt="Count and list all distinct objects you can see",
                model_name="llava"
            )
        )
        
        analyze_colors_task = Task(
            id="colors",
            name="Analyze Colors",
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                image_path="test_image.jpg",
                prompt="Describe the main colors and lighting in this image",
                model_name="llava"
            )
        )
        
        # Summary task that depends on all vision analyses
        summary_task = Task(
            id="summary",
            name="Create Summary",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="""Create a comprehensive summary based on these image analyses:
                
Description: {{describe.result}}
Objects: {{count.result}}  
Colors: {{colors.result}}

Provide a cohesive summary of the image.""",
                model_name="llama3"
            ),
            dependencies=["describe", "count", "colors"]
        )
        
        workflow = Workflow(
            name="Multi-Aspect Image Analysis",
            description="Analyze image from multiple perspectives",
            tasks=[describe_task, count_objects_task, analyze_colors_task, summary_task]
        )
        
        print("🚀 Running multi-aspect image analysis...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Monitor progress
        completed = set()
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            
            # Show progress
            current_completed = set(status.get("completed_tasks", []))
            new_completed = current_completed - completed
            
            for task_id in new_completed:
                task_name = next((t.name for t in workflow.tasks if t.id == task_id), task_id)
                print(f"✅ Completed: {task_name}")
            
            completed = current_completed
            
            if status["status"] in ["completed", "failed"]:
                break
            
            await asyncio.sleep(2)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("\n📊 Complete Image Analysis:")
            print(f"   📝 Description: {results.get('describe', 'N/A')[:100]}...")
            print(f"   🔢 Object count: {results.get('count', 'N/A')[:100]}...")
            print(f"   🎨 Colors: {results.get('colors', 'N/A')[:100]}...")
            print(f"   📋 Summary: {results.get('summary', 'N/A')}")
        else:
            error = status.get("error", "Unknown error")
            print(f"❌ Multi-image analysis failed: {error}")
    
    finally:
        await cluster.stop()


async def document_ocr_workflow():
    """OCR-style document processing workflow"""
    
    print("\n📄 Document OCR Workflow")
    print("=" * 40)
    
    cluster = GleitzeitCluster(
        enable_redis=False,
        enable_socketio=False,
        enable_real_execution=True
    )
    
    await cluster.start()
    
    try:
        # Extract text from document image
        ocr_task = Task(
            id="ocr",
            name="Extract Text",
            task_type=TaskType.VISION,
            parameters=TaskParameters(
                image_path="document.png",  # Assumes document image
                prompt="Extract all text from this document. Preserve formatting where possible.",
                model_name="llava"
            )
        )
        
        # Summarize extracted text
        summarize_task = Task(
            id="summarize",
            name="Summarize Document",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Summarize the key points from this extracted text: {{ocr.result}}",
                model_name="llama3"
            ),
            dependencies=["ocr"]
        )
        
        # Extract key information
        extract_info_task = Task(
            id="extract",
            name="Extract Key Info",
            task_type=TaskType.TEXT,
            parameters=TaskParameters(
                prompt="Extract important dates, names, numbers, and key facts from: {{ocr.result}}",
                model_name="llama3"
            ),
            dependencies=["ocr"]
        )
        
        workflow = Workflow(
            name="Document OCR Processing",
            description="Extract text and analyze document content",
            tasks=[ocr_task, summarize_task, extract_info_task]
        )
        
        print("🚀 Processing document...")
        workflow_id = await cluster.submit_workflow(workflow)
        
        # Monitor progress
        while True:
            status = await cluster.get_workflow_status(workflow_id)
            if status["status"] in ["completed", "failed"]:
                break
            await asyncio.sleep(2)
        
        if status["status"] == "completed":
            results = status.get("task_results", {})
            print("✅ Document processing completed:")
            print(f"   📄 Extracted text: {results.get('ocr', 'N/A')[:200]}...")
            print(f"   📋 Summary: {results.get('summarize', 'N/A')}")
            print(f"   🔍 Key info: {results.get('extract', 'N/A')}")
        else:
            error = status.get("error", "Unknown error")
            print(f"❌ Document processing failed: {error}")
            if "No such file" in str(error):
                print("   💡 Create a document.png file or update the image_path")
    
    finally:
        await cluster.stop()


async def main():
    """Run all vision demos"""
    
    print("📷 Gleitzeit Vision Capabilities Demo")
    print("=" * 60)
    print("⚠️  Prerequisites:")
    print("   • Ollama: curl -fsSL https://ollama.ai/install.sh | sh")
    print("   • Llava model: ollama pull llava")
    print("   • Test images: test_image.jpg, document.png")
    print()
    
    # Run vision demos
    await simple_vision_analysis()
    
    print("\n" + "="*60)
    print("🚀 Advanced demos (uncomment to run with real images):")
    print("   # await multi_image_workflow()")
    print("   # await document_ocr_workflow()")
    
    # Uncomment these when you have test images
    # await multi_image_workflow()
    # await document_ocr_workflow()
    
    print("\n✅ Vision demo overview completed!")
    print("\n💡 Key Vision Features:")
    print("   ✅ Image analysis with natural language prompts")
    print("   ✅ OCR and document processing")
    print("   ✅ Multi-aspect image analysis workflows")
    print("   ✅ Integration with text generation tasks")
    print("   ✅ Support for various image formats")
    print("\n🔍 Try with CLI: gleitzeit run --vision image.jpg --prompt 'Describe this image'")


if __name__ == "__main__":
    asyncio.run(main())