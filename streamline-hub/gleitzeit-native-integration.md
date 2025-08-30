# Gleitzeit-Native Hub System Integration

## 🎯 **Self-Hosting: Use Gleitzeit to Manage Gleitzeit!**

Instead of external task queues like Celery, we can use Gleitzeit's own workflow engine to manage hub operations. This creates a **self-healing, self-managing system** where Gleitzeit workflows handle:

- Health monitoring tasks
- Resource provisioning workflows  
- Auto-scaling decisions
- Load balancing optimization
- System maintenance tasks

## 🏗️ **Architecture: Gleitzeit Managing Gleitzeit**

```python
"""
Gleitzeit Hub System using native Gleitzeit workflows
"""

from gleitzeit.core.workflow import Workflow, Task
from gleitzeit.core.execution_engine import ExecutionEngine
from gleitzeit.providers.python_provider_v2 import PythonProviderV2
from gleitzeit.hub.base import ResourceHub
import asyncio
from typing import Dict, List, Any
from datetime import datetime, timedelta

class GleitzeitManagedHub:
    """
    Hub system that uses Gleitzeit workflows to manage itself
    """
    
    def __init__(self, execution_engine: ExecutionEngine):
        self.engine = execution_engine
        self.python_provider = PythonProviderV2(
            provider_id="hub_management",
            allow_local=True,
            allow_threads=True
        )
        
        # Register our management provider with the engine
        self.engine.register_provider("python", self.python_provider)
        
        # Active management workflows
        self.management_workflows = {}
        self.resource_registry = {}
        
    async def initialize(self):
        """Initialize the self-managing hub system"""
        await self.engine.initialize()
        await self.python_provider.initialize()
        
        # Start core management workflows
        await self._start_core_workflows()
    
    async def _start_core_workflows(self):
        """Start the core self-management workflows"""
        
        # 1. Health monitoring workflow (runs every 30 seconds)
        health_workflow = self._create_health_monitoring_workflow()
        health_task_id = await self.engine.submit_workflow(health_workflow)
        self.management_workflows['health_monitoring'] = health_task_id
        
        # 2. Resource optimization workflow (runs every 5 minutes)
        optimization_workflow = self._create_optimization_workflow()
        opt_task_id = await self.engine.submit_workflow(optimization_workflow)
        self.management_workflows['resource_optimization'] = opt_task_id
        
        # 3. Auto-scaling workflow (runs every 1 minute)
        scaling_workflow = self._create_scaling_workflow()
        scaling_task_id = await self.engine.submit_workflow(scaling_workflow)
        self.management_workflows['auto_scaling'] = scaling_task_id
        
        # 4. System maintenance workflow (runs daily)
        maintenance_workflow = self._create_maintenance_workflow()
        maint_task_id = await self.engine.submit_workflow(maintenance_workflow)
        self.management_workflows['maintenance'] = maint_task_id
        
        print("Started Gleitzeit self-management workflows")

    def _create_health_monitoring_workflow(self) -> Workflow:
        """Create workflow that monitors resource health"""
        
        workflow = Workflow(
            name="hub_health_monitoring",
            description="Monitor health of all resources in the hub",
            schedule="*/30 * * * * *",  # Every 30 seconds
            retry_policy={
                'max_retries': 3,
                'retry_delay': 5,
                'exponential_backoff': True
            }
        )
        
        # Task 1: Discover all resources
        discover_task = Task(
            name="discover_resources",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/discover_resources.py",
                "execution_mode": "thread"
            }
        )
        workflow.add_task(discover_task)
        
        # Task 2: Check health of discovered resources (parallel)
        health_check_task = Task(
            name="check_resource_health",
            provider="python", 
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/parallel_health_check.py",
                "execution_mode": "thread",
                "args": ["{{discover_resources.output}}"]  # Use output from previous task
            },
            depends_on=["discover_resources"]
        )
        workflow.add_task(health_check_task)
        
        # Task 3: Update resource status based on health results
        update_status_task = Task(
            name="update_resource_status",
            provider="python",
            method="execute_file", 
            parameters={
                "file_path": "/gleitzeit/hub_scripts/update_resource_status.py",
                "execution_mode": "thread",
                "args": ["{{check_resource_health.output}}"]
            },
            depends_on=["check_resource_health"]
        )
        workflow.add_task(update_status_task)
        
        # Task 4: Trigger alerts for unhealthy resources
        alert_task = Task(
            name="trigger_alerts",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/trigger_health_alerts.py", 
                "execution_mode": "thread",
                "args": ["{{update_resource_status.output}}"]
            },
            depends_on=["update_resource_status"]
            # Note: Conditional logic handled within the Python script
            # Script checks unhealthy_count > 0 and exits early if no alerts needed
        )
        workflow.add_task(alert_task)
        
        return workflow

    def _create_optimization_workflow(self) -> Workflow:
        """Create workflow that optimizes resource allocation"""
        
        workflow = Workflow(
            name="hub_resource_optimization",
            description="Optimize resource allocation and load balancing",
            schedule="0 */5 * * * *",  # Every 5 minutes
            retry_policy={'max_retries': 2}
        )
        
        # Task 1: Collect performance metrics
        metrics_task = Task(
            name="collect_metrics",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/collect_performance_metrics.py",
                "execution_mode": "thread"
            }
        )
        workflow.add_task(metrics_task)
        
        # Task 2: Analyze resource utilization patterns
        analysis_task = Task(
            name="analyze_utilization",
            provider="python", 
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/analyze_resource_utilization.py",
                "execution_mode": "thread",
                "args": ["{{collect_metrics.output}}"]
            },
            depends_on=["collect_metrics"]
        )
        workflow.add_task(analysis_task)
        
        # Task 3: Optimize load balancing weights
        optimization_task = Task(
            name="optimize_load_balancing", 
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/optimize_load_balancing.py",
                "execution_mode": "thread", 
                "args": ["{{analyze_utilization.output}}"]
            },
            depends_on=["analyze_utilization"]
        )
        workflow.add_task(optimization_task)
        
        # Task 4: Apply optimizations
        apply_task = Task(
            name="apply_optimizations",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/apply_optimizations.py",
                "execution_mode": "thread",
                "args": ["{{optimize_load_balancing.output}}"]
            },
            depends_on=["optimize_load_balancing"]
        )
        workflow.add_task(apply_task)
        
        return workflow

    def _create_scaling_workflow(self) -> Workflow:
        """Create workflow that handles auto-scaling decisions"""
        
        workflow = Workflow(
            name="hub_auto_scaling",
            description="Monitor load and auto-scale resources",
            schedule="0 * * * * *",  # Every minute
            retry_policy={'max_retries': 2}
        )
        
        # Task 1: Assess current load
        load_assessment_task = Task(
            name="assess_current_load",
            provider="python",
            method="execute_file", 
            parameters={
                "file_path": "/gleitzeit/hub_scripts/assess_system_load.py",
                "execution_mode": "thread"
            }
        )
        workflow.add_task(load_assessment_task)
        
        # Task 2: Scale up if needed (conditional logic in script)
        scale_up_task = Task(
            name="scale_up_resources",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/scale_up_resources.py",
                "execution_mode": "thread",
                "args": ["{{assess_current_load.output}}"]
            },
            depends_on=["assess_current_load"]
            # Note: Script checks if cpu_utilization > 80 or memory_utilization > 85
            # and exits early if scaling not needed
        )
        workflow.add_task(scale_up_task)
        
        # Task 3: Scale down if needed (conditional logic in script)
        scale_down_task = Task(
            name="scale_down_resources",
            provider="python", 
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/scale_down_resources.py",
                "execution_mode": "thread",
                "args": ["{{assess_current_load.output}}"]
            },
            depends_on=["assess_current_load"]
            # Note: Script checks if cpu_utilization < 20 and memory_utilization < 30
            # and exits early if scaling down not needed
        )
        workflow.add_task(scale_down_task)
        
        return workflow

    def _create_maintenance_workflow(self) -> Workflow:
        """Create workflow for system maintenance tasks"""
        
        workflow = Workflow(
            name="hub_system_maintenance",
            description="Daily system maintenance and cleanup",
            schedule="0 2 * * *",  # Daily at 2 AM
            retry_policy={'max_retries': 1}
        )
        
        # Task 1: Clean up old metrics
        cleanup_metrics_task = Task(
            name="cleanup_old_metrics",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/cleanup_old_metrics.py",
                "execution_mode": "thread"
            }
        )
        workflow.add_task(cleanup_metrics_task)
        
        # Task 2: Optimize database
        db_optimization_task = Task(
            name="optimize_database",
            provider="python", 
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/optimize_database.py",
                "execution_mode": "thread"
            },
            depends_on=["cleanup_old_metrics"]
        )
        workflow.add_task(db_optimization_task)
        
        # Task 3: Generate system health report
        health_report_task = Task(
            name="generate_health_report",
            provider="python",
            method="execute_file", 
            parameters={
                "file_path": "/gleitzeit/hub_scripts/generate_health_report.py",
                "execution_mode": "thread"
            },
            depends_on=["optimize_database"]
        )
        workflow.add_task(health_report_task)
        
        return workflow

    async def register_resource(self, resource_data: Dict[str, Any]):
        """Register a new resource and trigger management workflows"""
        
        # Store resource in registry
        resource_id = resource_data['id']
        self.resource_registry[resource_id] = resource_data
        
        # Trigger immediate health check for new resource
        immediate_check_workflow = Workflow(
            name=f"immediate_health_check_{resource_id}",
            description=f"Immediate health check for new resource {resource_id}"
        )
        
        check_task = Task(
            name="check_new_resource",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/check_single_resource.py",
                "execution_mode": "thread", 
                "args": [resource_data]
            }
        )
        immediate_check_workflow.add_task(check_task)
        
        # Submit workflow
        task_id = await self.engine.submit_workflow(immediate_check_workflow)
        return task_id

    async def get_resource(self, resource_type: str, **filters) -> Dict[str, Any]:
        """Get best available resource using Gleitzeit workflow"""
        
        # Create resource selection workflow
        selection_workflow = Workflow(
            name="resource_selection",
            description=f"Select best {resource_type} resource"
        )
        
        selection_task = Task(
            name="select_best_resource",
            provider="python",
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/select_best_resource.py",
                "execution_mode": "thread",
                "args": [resource_type, filters]
            }
        )
        selection_workflow.add_task(selection_task)
        
        # Execute workflow and wait for result
        task_id = await self.engine.submit_workflow(selection_workflow)
        result = await self.engine.wait_for_completion(task_id)
        
        if result.status == 'completed':
            return result.outputs['select_best_resource']
        else:
            raise Exception(f"Resource selection failed: {result.error}")

    async def get_system_status(self) -> Dict[str, Any]:
        """Get current system status using workflow"""
        
        status_workflow = Workflow(
            name="system_status_check",
            description="Get comprehensive system status"
        )
        
        # Parallel status checks
        status_tasks = [
            Task(
                name="resource_status",
                provider="python",
                method="execute_file", 
                parameters={
                    "file_path": "/gleitzeit/hub_scripts/get_resource_status.py",
                    "execution_mode": "thread"
                }
            ),
            Task(
                name="performance_status",
                provider="python",
                method="execute_file",
                parameters={
                    "file_path": "/gleitzeit/hub_scripts/get_performance_status.py", 
                    "execution_mode": "thread"
                }
            ),
            Task(
                name="workflow_status", 
                provider="python",
                method="execute_file",
                parameters={
                    "file_path": "/gleitzeit/hub_scripts/get_workflow_status.py",
                    "execution_mode": "thread"
                }
            )
        ]
        
        for task in status_tasks:
            status_workflow.add_task(task)
        
        # Aggregation task
        aggregate_task = Task(
            name="aggregate_status",
            provider="python", 
            method="execute_file",
            parameters={
                "file_path": "/gleitzeit/hub_scripts/aggregate_system_status.py",
                "execution_mode": "thread",
                "args": [
                    "{{resource_status.output}}",
                    "{{performance_status.output}}", 
                    "{{workflow_status.output}}"
                ]
            },
            depends_on=["resource_status", "performance_status", "workflow_status"]
        )
        status_workflow.add_task(aggregate_task)
        
        # Execute and return result
        task_id = await self.engine.submit_workflow(status_workflow)
        result = await self.engine.wait_for_completion(task_id)
        
        return result.outputs['aggregate_status']

    async def shutdown(self):
        """Gracefully shutdown the self-managing hub"""
        
        # Cancel all management workflows
        for workflow_name, task_id in self.management_workflows.items():
            try:
                await self.engine.cancel_task(task_id)
                print(f"Cancelled {workflow_name} workflow")
            except Exception as e:
                print(f"Error cancelling {workflow_name}: {e}")
        
        await self.python_provider.shutdown()
        await self.engine.shutdown()
```

## 📁 **Management Scripts Structure**

```
/gleitzeit/hub_scripts/
├── discover_resources.py          # Find all available resources
├── parallel_health_check.py       # Check health of multiple resources
├── update_resource_status.py      # Update resource status in registry
├── trigger_health_alerts.py       # Send alerts for unhealthy resources
├── collect_performance_metrics.py # Gather system performance data
├── analyze_resource_utilization.py # Analyze usage patterns
├── optimize_load_balancing.py      # Optimize load balancing algorithms
├── apply_optimizations.py         # Apply system optimizations
├── assess_system_load.py          # Check if scaling is needed
├── scale_up_resources.py          # Provision new resources
├── scale_down_resources.py        # Decommission excess resources
├── cleanup_old_metrics.py         # Clean up historical data
├── optimize_database.py           # Database maintenance tasks
├── generate_health_report.py      # Create system health reports
├── check_single_resource.py       # Health check single resource
├── select_best_resource.py        # Intelligent resource selection
├── get_resource_status.py         # Get resource status summary
├── get_performance_status.py      # Get performance metrics
├── get_workflow_status.py         # Get workflow execution status
└── aggregate_system_status.py     # Combine all status information
```

## 🎯 **Usage Example**

```python
"""
Using Gleitzeit to manage its own hub system
"""

async def demo_self_managing_hub():
    # Initialize Gleitzeit execution engine
    engine = ExecutionEngine()
    await engine.initialize()
    
    # Create self-managing hub
    hub = GleitzeitManagedHub(engine)
    await hub.initialize()
    
    print("Gleitzeit is now managing itself!")
    print("Active management workflows:")
    for name in hub.management_workflows:
        print(f"  - {name}")
    
    # Register a new Docker resource
    await hub.register_resource({
        'id': 'docker_node_1',
        'type': 'docker',
        'endpoint': 'http://docker-node-1:2376',
        'region': 'us-east-1'
    })
    
    # Get best available Docker resource (uses workflow)
    best_docker = await hub.get_resource('docker', region='us-east-1')
    print(f"Selected Docker resource: {best_docker['id']}")
    
    # Get comprehensive system status (uses workflow)
    status = await hub.get_system_status()
    print(f"System status: {status['overall_health']}")
    print(f"Active resources: {status['resource_count']}")
    print(f"CPU utilization: {status['cpu_utilization']}%")
    
    # The hub will continue managing itself through workflows:
    # - Health checks every 30 seconds
    # - Resource optimization every 5 minutes  
    # - Auto-scaling decisions every minute
    # - Daily maintenance at 2 AM
    
    # Let it run for a while to see self-management in action
    await asyncio.sleep(300)  # 5 minutes
    
    await hub.shutdown()
```

## 🚀 **Benefits of Native Integration**

### 1. **Self-Healing System**
- Health monitoring workflows detect and recover from failures
- Auto-scaling workflows prevent resource exhaustion
- Maintenance workflows prevent degradation over time

### 2. **Unified Monitoring**
- Hub management tasks appear in Gleitzeit's own workflow dashboard
- Same monitoring, logging, and alerting for hub operations
- Consistent retry policies and error handling

### 3. **Intelligent Scheduling**
- Cron-based scheduling for regular maintenance
- Python-based conditional logic within scripts for system state decisions
- Dependency management between management tasks

### 4. **Scalable Architecture**
- Management workflows can run on different Gleitzeit instances
- Distributed processing of hub operations
- Load balancing of management tasks

### 5. **Extensible**
- Easy to add new management workflows
- Python scripts can be version controlled and tested
- Integration with existing Gleitzeit provider ecosystem

## 🎉 **The Meta-Loop: Gleitzeit Managing Gleitzeit**

This creates a beautiful meta-system where:
1. **Gleitzeit workflows** monitor hub health
2. **Gleitzeit tasks** optimize resource allocation  
3. **Gleitzeit schedules** handle maintenance
4. **Gleitzeit providers** execute management operations
5. **Gleitzeit engine** coordinates everything

The system becomes **truly self-managing** - Gleitzeit uses its own capabilities to optimize and scale itself! 🔄✨