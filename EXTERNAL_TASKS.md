# Socket.IO External Task System

## Overview

The Socket.IO External Task System allows external services to integrate with Gleitzeit as first-class task executors. External services can register with the cluster, receive task assignments, and execute tasks seamlessly alongside internal cluster nodes.

## Architecture

```
┌─────────────────┐    Socket.IO    ┌──────────────────┐
│ Gleitzeit       │◄──────────────►│ External         │
│ Cluster         │   Real-time     │ Service          │
│                 │   Task Dispatch │                  │
│ • Task Queue    │                 │ • ML Training    │
│ • Scheduler     │                 │ • API Calls      │
│ • Monitoring    │                 │ • Database Ops   │
│ • Recovery      │                 │ • Custom Logic   │
└─────────────────┘                 └──────────────────┘
```

## Key Features

### ✅ **Implemented Core Features**

- **🔗 Socket.IO Integration**: Real-time bidirectional communication
- **📋 External Task Types**: 6 built-in external task types
- **🎯 Intelligent Routing**: Automatic task dispatch to appropriate services
- **🔄 Dependency Resolution**: External tasks work seamlessly with internal task dependencies
- **📊 Real-time Monitoring**: External services visible in monitoring dashboard
- **⚡ Event-driven**: No polling overhead, pure event-based architecture
- **🛡️ Recovery Support**: External tasks integrate with cluster recovery system
- **🏗️ Workflow Builder**: Convenient methods for creating external tasks

### **External Task Types**

1. **`EXTERNAL_ML`**: Machine learning training and inference
2. **`EXTERNAL_API`**: HTTP API calls and integrations
3. **`EXTERNAL_DATABASE`**: Database operations and queries
4. **`EXTERNAL_PROCESSING`**: Data processing and transformations
5. **`EXTERNAL_WEBHOOK`**: Webhook-based asynchronous tasks
6. **`EXTERNAL_CUSTOM`**: Custom service integrations

## Quick Start

### 1. Create External Service

```python
#!/usr/bin/env python3
"""My External Service"""

import asyncio
from gleitzeit_cluster.core.external_service_node import (
    ExternalServiceNode, ExternalServiceCapability
)

# Your service logic
class MyService:
    async def handle_ml_training(self, task_data):
        # Your ML training logic here
        return {"model_id": "trained_model_123", "accuracy": 0.95}

# Create service node
service = MyService()
service_node = ExternalServiceNode(
    service_name="My ML Service",
    cluster_url="http://localhost:8000",
    capabilities=[ExternalServiceCapability.ML_TRAINING]
)

# Register handlers
service_node.register_task_handler("ml_training", service.handle_ml_training)

# Start service
asyncio.run(service_node.start())
```

### 2. Use External Tasks in Workflows

```python
#!/usr/bin/env python3
"""Workflow with External Tasks"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster

async def main():
    cluster = GleitzeitCluster()
    await cluster.start()
    
    # Create hybrid workflow
    workflow = cluster.create_workflow("Hybrid ML Pipeline")
    
    # Internal task
    data_prep = workflow.add_python_task(
        "Prepare Data", 
        function_name="prepare_dataset"
    )
    
    # External ML task
    ml_training = workflow.add_external_ml_task(
        name="Train Model",
        service_name="My ML Service", 
        operation="train",
        model_params={"algorithm": "xgboost"},
        data_params={"data": "{{Prepare Data.result}}"},
        dependencies=["Prepare Data"]
    )
    
    # Internal task using external results
    report = workflow.add_text_task(
        "Generate Report",
        prompt="Model results: {{Train Model.result}}",
        dependencies=["Train Model"]  
    )
    
    # Execute workflow
    workflow_id = await cluster.submit_workflow(workflow)
    
asyncio.run(main())
```

## External Service Capabilities

```python
class ExternalServiceCapability(Enum):
    ML_TRAINING = "ml_training"           # ML model training
    ML_INFERENCE = "ml_inference"         # ML inference/prediction  
    DATA_PROCESSING = "data_processing"   # ETL and data transformation
    API_INTEGRATION = "api_integration"   # HTTP API calls
    DATABASE_OPERATIONS = "database_operations"  # DB queries/updates
    FILE_PROCESSING = "file_processing"   # File operations
    WEBHOOK_HANDLING = "webhook_handling" # Async webhook processing
    CUSTOM_PROCESSING = "custom_processing"  # Custom logic
```

## Workflow Builder Methods

### **External ML Tasks**
```python
workflow.add_external_ml_task(
    name="Train Model",
    service_name="ML Service",
    operation="train",  # "train", "inference", "evaluate"
    model_params={"model_type": "xgboost"},
    data_params={"dataset": "training.csv"},
    timeout=3600  # 1 hour
)
```

### **External API Tasks**
```python
workflow.add_external_api_task(
    name="Call External API",
    service_name="API Service", 
    endpoint="/process",
    method="POST",
    payload={"data": "{{Previous Task.result}}"},
    headers={"Authorization": "Bearer token"}
)
```

### **External Database Tasks**
```python
workflow.add_external_database_task(
    name="Query Database",
    service_name="DB Service",
    operation="query",
    query_params={
        "table": "users",
        "conditions": {"active": True}
    }
)
```

### **Generic External Tasks**
```python
workflow.add_external_task(
    name="Custom Processing",
    external_task_type="custom_processing",
    service_name="Custom Service",
    external_parameters={"custom_param": "value"}
)
```

## Real-time Monitoring

External services are fully integrated into the monitoring system:

```bash
# Monitor external services in real-time
python gleitzeit_cluster/cli_monitor_live.py
```

**Monitoring displays:**
- 🔗 External service status and health
- 📊 Task completion rates and success rates  
- ⏱️ Service uptime and availability
- 🎯 Current task load and capacity
- 🔧 Service capabilities and task types

## Event-driven Architecture

The system uses pure event-driven communication:

### **Service → Cluster Events**
- `task:accepted` - Service accepts task assignment
- `task:progress` - Real-time task progress updates  
- `task:completed` - Task completion with results
- `task:failed` - Task failure with error details
- `node:heartbeat` - Service health and metrics

### **Cluster → Service Events**  
- `task:assign` - New task assignment
- `task:cancel` - Task cancellation request
- `cluster:shutdown` - Cluster shutdown notification

## Dependency Resolution

External tasks work seamlessly with Gleitzeit's dependency system:

```python
# Internal task
data_task = workflow.add_python_task("Get Data", "fetch_data")

# External task depending on internal task  
ml_task = workflow.add_external_ml_task(
    "Train Model",
    service_name="ML Service",
    data_params={"input": "{{Get Data.result}}"},  # ✅ Works!
    dependencies=["Get Data"]
)

# Internal task depending on external task
report_task = workflow.add_text_task(
    "Generate Report", 
    prompt="Results: {{Train Model.result}}",  # ✅ Works!
    dependencies=["Train Model"]
)
```

## Recovery & Persistence  

External tasks integrate with the cluster recovery system:

- **Redis Persistence**: External task states stored in Redis
- **Automatic Recovery**: External tasks resume after cluster restart
- **Parameter Resolution**: `{{task.result}}` references resolved during recovery
- **Task Dispatch**: Recovered external tasks automatically assigned to services

## Example Services

The repository includes complete example services:

- **`examples/external_ml_service.py`**: ML training and inference service
- **`examples/external_api_service.py`**: API integration service  
- **`examples/external_task_demo.py`**: Complete hybrid workflow demo

## Testing

Run the test suite to verify the implementation:

```bash
python examples/test_external_tasks.py
```

## Benefits

### 🚀 **Scalability**
- **Horizontal scaling**: Add external services as needed
- **Resource distribution**: Offload intensive work to dedicated services
- **Technology diversity**: Integrate services in any language/platform

### 🔗 **Integration**  
- **Existing services**: No need to rewrite existing systems
- **Gradual migration**: Incrementally move logic to external services  
- **Service mesh**: Build complex service architectures

### ⚡ **Performance**
- **Real-time communication**: No polling overhead
- **Parallel execution**: External services run concurrently  
- **Resource optimization**: Right-sized services for specific tasks

### 🛡️ **Reliability**
- **Fault isolation**: External service failures don't crash cluster
- **Automatic recovery**: Services reconnect and resume automatically
- **Circuit breakers**: Built-in error handling and retry logic

### 📊 **Observability**  
- **Unified monitoring**: All services visible in single dashboard
- **Real-time metrics**: Live task execution monitoring
- **Centralized logging**: All events flow through cluster

## Architecture Integration

The external task system integrates seamlessly with existing Gleitzeit components:

- **Task Dispatcher**: Routes external tasks to appropriate services
- **Socket.IO Server**: Handles bidirectional communication  
- **Monitoring System**: Tracks external service health and metrics
- **Recovery System**: Includes external tasks in recovery workflows
- **Error Registry**: Comprehensive error handling for external services

## Next Steps

The external task system provides a solid foundation for:

- **Microservice orchestration**: Coordinate complex service interactions
- **Hybrid cloud deployments**: Mix on-premise and cloud services
- **AI/ML pipelines**: Integrate specialized ML infrastructure  
- **Data processing workflows**: Connect with big data systems
- **API mashups**: Combine multiple external APIs in workflows

---

The Socket.IO External Task System transforms Gleitzeit from a single-cluster orchestrator into a powerful distributed workflow platform that can coordinate any number of external services while maintaining the simplicity and reliability of the core system.