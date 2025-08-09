#!/usr/bin/env python3
"""
External Task Integration Demo

Demonstrates the complete Socket.IO external task system:
1. External services integrated as task executors
2. Hybrid workflows mixing internal and external tasks
3. Dependency resolution across service boundaries
4. Real-time monitoring of external task execution
5. Parameter passing and result chaining
"""

import asyncio
import sys
from pathlib import Path

# Add the parent directory to the path so we can import gleitzeit_cluster
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster, Workflow


async def demo_external_tasks():
    """Demonstrate external task integration"""
    
    print("🌐 External Task Integration Demo")
    print("=" * 50)
    
    # Create cluster with full external task support
    cluster = GleitzeitCluster(
        enable_redis=True,
        enable_real_execution=True,
        enable_socketio=True,
        auto_start_socketio_server=True,
        socketio_host="0.0.0.0",
        socketio_port=8000,
        auto_start_services=True,
        auto_recovery=True
    )
    
    try:
        print("\\n🚀 Starting cluster with external task support...")
        await cluster.start()
        
        print("\\n🔗 External Task Features:")
        print("   ✅ Socket.IO external service integration")
        print("   ✅ Hybrid workflows (internal + external tasks)")
        print("   ✅ Cross-service dependency resolution")
        print("   ✅ Real-time external task monitoring")
        print("   ✅ Parameter chaining with {{task.result}}")
        print("   ✅ Extended timeouts for long-running external tasks")
        
        # Wait for external services to connect
        print("\\n⏳ Waiting for external services to register...")
        print("   Make sure external ML service is running:")
        print("   python examples/external_ml_service.py")
        
        await asyncio.sleep(5)
        
        # Check if any external services are connected
        external_services = 0
        if cluster.socketio_server:
            external_services = len(cluster.socketio_server.external_service_nodes)
            
        if external_services == 0:
            print("\\n⚠️  No external services connected.")
            print("   This demo will show the workflow structure, but external tasks won't execute.")
            print("   Start the ML service in another terminal to see full integration.")
        else:
            print(f"\\n✅ Found {external_services} external service(s) connected!")
        
        # Create hybrid workflow with internal and external tasks
        print("\\n📋 Creating hybrid workflow (internal + external tasks)...")
        
        workflow = cluster.create_workflow(
            name="Hybrid ML Pipeline",
            description="Workflow combining internal data prep with external ML processing"
        )
        
        # Step 1: Internal task - data preparation
        data_prep = workflow.add_python_task(
            name="Prepare Training Data",
            function_name="random_data",
            kwargs={
                "data_type": "numbers",
                "count": 1000,
                "min": 1,
                "max": 100
            }
        )
        
        # Step 2: External ML task - model training (depends on data prep)
        ml_training = workflow.add_external_ml_task(
            name="Train ML Model",
            service_name="Mock ML Service",
            operation="train",
            model_params={
                "model_type": "random_forest",
                "n_estimators": 50
            },
            data_params={
                "n_samples": 800,
                "n_features": 10,
                "n_classes": 2
            },
            dependencies=["Prepare Training Data"],
            timeout=3600  # 1 hour timeout for training
        )
        
        # Step 3: External ML task - model inference (depends on training)  
        ml_inference = workflow.add_external_ml_task(
            name="Run Model Inference",
            service_name="Mock ML Service",
            operation="inference",
            model_params={
                "model_id": "{{Train ML Model.result.model_id}}",  # Use result from training
                "n_samples": 100
            },
            dependencies=["Train ML Model"],
            timeout=600  # 10 minute timeout for inference
        )
        
        # Step 4: Internal task - analyze ML results
        results_analysis = workflow.add_python_task(
            name="Analyze ML Results",
            function_name="analyze_numbers",
            kwargs={
                "numbers": "{{Run Model Inference.result.predictions}}"  # Use inference results
            },
            dependencies=["Run Model Inference"]
        )
        
        # Step 5: External API task - send results to external system
        api_notification = workflow.add_external_api_task(
            name="Send Results Notification",
            service_name="API Service",
            endpoint="/ml-results",
            method="POST",
            payload={
                "model_accuracy": "{{Train ML Model.result.accuracy}}",
                "inference_count": "{{Run Model Inference.result.n_samples}}",
                "analysis_summary": "{{Analyze ML Results.result}}"
            },
            dependencies=["Analyze ML Results"],
            timeout=60  # 1 minute timeout for API call
        )
        
        # Step 6: Internal task - final report generation
        final_report = workflow.add_text_task(
            name="Generate Final Report",
            prompt='''Create a comprehensive ML pipeline report:

Training Results: {{Train ML Model.result}}
Inference Results: {{Run Model Inference.result}}  
Analysis: {{Analyze ML Results.result}}
API Response: {{Send Results Notification.result}}

Provide insights and recommendations.''',
            model="llama3",
            dependencies=["Send Results Notification"]
        )
        
        print(f"   ✅ Created hybrid workflow with {len(workflow.tasks)} tasks:")
        for task_name, task in workflow.tasks.items():
            task_type = "🔗 External" if str(task.task_type).startswith("TaskType.EXTERNAL") else "🏠 Internal"
            deps = ', '.join(task.dependencies) if task.dependencies else 'none'
            timeout_info = f" (timeout: {task.timeout_seconds}s)" if task.timeout_seconds != 300 else ""
            print(f"   {task_type} {task.name} (depends on: {deps}){timeout_info}")
        
        # Submit workflow
        workflow_id = await cluster.submit_workflow(workflow)
        print(f"\\n📤 Submitted hybrid workflow: {workflow_id[:12]}...")
        
        print("\\n🔄 Workflow Execution Flow:")
        print("   1. 🏠 Prepare Training Data (internal Python function)")
        print("   2. 🔗 Train ML Model (external ML service)")
        print("   3. 🔗 Run Model Inference (external ML service)")
        print("   4. 🏠 Analyze ML Results (internal Python function)")
        print("   5. 🔗 Send Results Notification (external API service)")  
        print("   6. 🏠 Generate Final Report (internal LLM)")
        
        print("\\n📡 External Task Features Demonstrated:")
        print("   • Socket.IO communication between cluster and external services")
        print("   • Dependency resolution across service boundaries")
        print("   • Parameter substitution with {{external_task.result}}")
        print("   • Extended timeouts for long-running external operations")
        print("   • Real-time progress monitoring of external tasks")
        print("   • Seamless integration with internal task recovery system")
        
        if external_services > 0:
            print("\\n⏳ Watching workflow execution...")
            print("   External tasks will be dispatched to connected services")
            print("   Monitor progress in real-time with:")
            print("   python gleitzeit_cluster/cli_monitor_live.py")
            
            # Wait for workflow to progress
            await asyncio.sleep(30)
            
            # Check workflow status
            if cluster.redis_client:
                try:
                    status = await cluster.get_workflow_status(workflow_id)
                    if status:
                        completed = status.get('completed_tasks', 0)
                        total = status.get('total_tasks', len(workflow.tasks))
                        print(f"\\n📊 Workflow Progress: {completed}/{total} tasks completed")
                        
                        if status.get('results'):
                            print("\\n✅ Task Results Preview:")
                            for task_name, result in list(status['results'].items())[:3]:
                                result_preview = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)
                                print(f"   {task_name}: {result_preview}")
                except Exception as e:
                    print(f"   Could not retrieve workflow status: {e}")
        
        print("\\n🔧 External Service Integration Architecture:")
        print("   ┌─────────────────┐    Socket.IO    ┌──────────────────┐")
        print("   │ Gleitzeit       │◄──────────────►│ External         │")
        print("   │ Cluster         │   Real-time     │ ML Service       │")
        print("   │                 │   Task Dispatch │                  │")
        print("   │ • Task Queue    │                 │ • Model Training │")
        print("   │ • Scheduler     │                 │ • Inference      │")
        print("   │ • Monitoring    │                 │ • Evaluation     │")
        print("   └─────────────────┘                 └──────────────────┘")
        
        print("\\n💡 External Task Benefits:")
        print("   🚀 Scale beyond single cluster - offload intensive work")
        print("   🔗 Integrate existing services - no code rewriting needed")
        print("   ⚡ Real-time communication - no polling overhead")
        print("   🔄 Automatic recovery - external tasks resume after interruption")
        print("   📊 Unified monitoring - all tasks visible in single dashboard")
        print("   🎯 Dependency management - external results feed internal tasks")
        
        print("\\n✅ External task integration demo completed!")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print("\\n🛑 Shutting down cluster...")
        await cluster.stop()


async def demo_external_task_patterns():
    """Demonstrate common external task patterns"""
    
    print("\\n" + "="*60)
    print("🎨 Common External Task Patterns")
    print("="*60)
    
    cluster = GleitzeitCluster()
    
    # Pattern 1: ML Pipeline
    ml_workflow = cluster.create_workflow("ML Pipeline Pattern")
    
    # Data prep → Training → Evaluation → Deployment
    data_prep = ml_workflow.add_python_task("Data Prep", "prepare_ml_data")
    
    training = ml_workflow.add_external_ml_task(
        "Model Training",
        service_name="ML Service",
        operation="train",
        dependencies=["Data Prep"]
    )
    
    evaluation = ml_workflow.add_external_ml_task(
        "Model Evaluation", 
        service_name="ML Service",
        operation="evaluate",
        model_params={"model_id": "{{Model Training.result.model_id}}"},
        dependencies=["Model Training"]
    )
    
    deployment = ml_workflow.add_external_api_task(
        "Deploy Model",
        service_name="Deployment Service", 
        endpoint="/deploy",
        payload={"model_id": "{{Model Training.result.model_id}}"},
        dependencies=["Model Evaluation"]
    )
    
    # Pattern 2: Data Processing Pipeline
    data_workflow = cluster.create_workflow("Data Processing Pattern")
    
    extract = data_workflow.add_external_database_task(
        "Extract Data",
        service_name="Database Service",
        operation="query"
    )
    
    transform = data_workflow.add_external_task(
        "Transform Data",
        external_task_type="data_processing",
        service_name="ETL Service",
        dependencies=["Extract Data"]
    )
    
    load = data_workflow.add_external_database_task(
        "Load Data",
        service_name="Warehouse Service",
        operation="batch_load",
        dependencies=["Transform Data"]
    )
    
    # Pattern 3: API Integration Chain
    api_workflow = cluster.create_workflow("API Integration Pattern")
    
    auth = api_workflow.add_external_api_task(
        "Authenticate",
        service_name="Auth Service",
        endpoint="/login"
    )
    
    fetch_data = api_workflow.add_external_api_task(
        "Fetch User Data",
        service_name="User Service",
        endpoint="/users",
        headers={"Authorization": "{{Authenticate.result.token}}"},
        dependencies=["Authenticate"]
    )
    
    process_data = api_workflow.add_python_task(
        "Process Data",
        function_name="process_users",
        kwargs={"users": "{{Fetch User Data.result}}"},
        dependencies=["Fetch User Data"]
    )
    
    notify = api_workflow.add_external_api_task(
        "Send Notification",
        service_name="Notification Service",
        endpoint="/notify", 
        payload={"processed_count": "{{Process Data.result.count}}"},
        dependencies=["Process Data"]
    )
    
    print("📋 External Task Patterns Created:")
    print(f"   🧠 ML Pipeline: {len(ml_workflow.tasks)} tasks")
    print(f"   📊 Data Processing: {len(data_workflow.tasks)} tasks") 
    print(f"   🔗 API Integration: {len(api_workflow.tasks)} tasks")
    
    print("\\n💡 These patterns show how external tasks enable:")
    print("   • Complex multi-service workflows")
    print("   • Seamless data flow between services")
    print("   • Flexible service composition")
    print("   • Unified orchestration across technology stacks")


if __name__ == "__main__":
    print("🌟 External Task System Demo")
    print()
    print("🔧 Prerequisites:")
    print("   1. Start Gleitzeit cluster: python examples/monitoring_demo.py")
    print("   2. Start ML service: python examples/external_ml_service.py")
    print("   3. Start monitoring: python gleitzeit_cluster/cli_monitor_live.py")
    print("   4. Run this demo: python examples/external_task_demo.py")
    print()
    print("Press Enter to start demo...")
    input()
    
    asyncio.run(demo_external_tasks())
    asyncio.run(demo_external_task_patterns())