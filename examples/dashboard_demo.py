#!/usr/bin/env python3
"""
Dashboard Demo - Start web GUI server with sample data

This demo starts the Socket.IO server with the web dashboard
and generates sample workflows to demonstrate real-time monitoring.

Usage:
    python examples/dashboard_demo.py

Then open: http://localhost:8000
"""

import asyncio
import sys
from pathlib import Path

# Add package to path for import
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster.core.cluster import GleitzeitCluster


async def main():
    """Start dashboard with demo data"""
    print("🚀 Gleitzeit Cluster - Web Dashboard Demo")
    print("=" * 50)
    
    cluster = GleitzeitCluster(
        enable_real_execution=False,  # Mock execution for demo
        enable_redis=True,
        enable_socketio=True,
        auto_start_socketio_server=True  # Auto-start Socket.IO server
    )
    
    try:
        await cluster.start()
        
        print()
        print("🌐 Web Dashboard Available:")
        print("   URL: http://localhost:8000")
        print("   Dashboard: http://localhost:8000/dashboard")
        print()
        print("📊 Dashboard Features:")
        print("   ✅ Real-time cluster statistics")
        print("   ✅ Live workflow monitoring")
        print("   ✅ Node status tracking")
        print("   ✅ Activity feed with events")
        print("   ✅ Professional dark theme UI")
        print()
        
        # Create some demo workflows to show in dashboard
        print("🔄 Creating demo workflows...")
        
        # Workflow 1: Simple analysis
        workflow1 = cluster.create_workflow(
            "document_analysis", 
            "Document analysis pipeline"
        )
        task1 = workflow1.add_text_task("extract", "Extract key points", "llama3")
        task2 = workflow1.add_text_task("summarize", "Create summary", "llama3", dependencies=[task1.id])
        
        # Workflow 2: Research workflow  
        workflow2 = cluster.create_workflow(
            "research_pipeline",
            "Research data processing"
        )
        task3 = workflow2.add_text_task("query", "Research query analysis", "llama3")
        task4 = workflow2.add_vision_task("chart", "Analyze research charts", "llava", dependencies=[task3.id])
        
        print("📋 Submitting workflows to demonstrate dashboard...")
        
        # Submit workflows (they will show in the dashboard)
        result1 = await cluster.execute_workflow(workflow1)
        print(f"✅ Workflow 1 completed: {result1.status.value}")
        
        result2 = await cluster.execute_workflow(workflow2)  
        print(f"✅ Workflow 2 completed: {result2.status.value}")
        
        print()
        print("🎯 Dashboard is now ready!")
        print("   Open http://localhost:8000 to view the dashboard")
        print("   The workflows above will be visible in the interface")
        print()
        print("⚡ Server will run for 2 minutes to demo dashboard...")
        print("   Press Ctrl+C to stop early")
        
        # Keep server running for demo
        await asyncio.sleep(120)  # 2 minutes
        
        print("\n🎯 Demo completed!")
        
    except KeyboardInterrupt:
        print("\n🛑 Demo stopped by user")
    except Exception as e:
        print(f"❌ Demo failed: {e}")
    finally:
        await cluster.stop()
        print("🔌 Dashboard server stopped")


if __name__ == "__main__":
    asyncio.run(main())