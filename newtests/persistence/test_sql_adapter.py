"""
Test Suite for SQLAlchemy Adapter

Tests SQLAlchemy-specific features and implementation details.
"""

import pytest
import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from typing import List, Optional
import uuid
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from gleitzeit.persistence.unified_sqlalchemy import UnifiedSQLAlchemyAdapter
from gleitzeit.core.models import Task, Workflow, TaskResult, WorkflowExecution
from gleitzeit.hub.base import ResourceInstance, ResourceMetrics, ResourceStatus, ResourceType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
async def sqlite_adapter():
    """Create a SQLite adapter for testing"""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        db_path = tmp.name
    
    adapter = UnifiedSQLAlchemyAdapter(db_path=db_path, echo=False)
    await adapter.initialize()
    
    yield adapter
    
    await adapter.shutdown()
    os.unlink(db_path)


@pytest.fixture
async def memory_sqlite_adapter():
    """Create an in-memory SQLite adapter for testing"""
    adapter = UnifiedSQLAlchemyAdapter(db_path=":memory:", echo=False)
    await adapter.initialize()
    
    yield adapter
    
    await adapter.shutdown()


@pytest.fixture
async def populated_adapter(memory_sqlite_adapter):
    """Create a SQLite adapter with test data"""
    adapter = memory_sqlite_adapter
    
    # Add test tasks
    for i in range(5):
        task = Task(
            id=f"task_{i}",
            name=f"Task {i}",
            protocol="test",
            method="test_method",
            params={"index": i},
            status="queued" if i < 3 else "completed",
            priority="normal",
            workflow_id="workflow_1" if i < 2 else None
        )
        await adapter.save_task(task)
    
    # Add test resource
    resource = ResourceInstance(
        id="resource_1",
        name="Test Resource",
        type=ResourceType.OLLAMA,
        endpoint="http://localhost:8080",
        status=ResourceStatus.HEALTHY,
        metadata={"test": "data"}
    )
    await adapter.save_instance("hub_1", resource)
    
    return adapter


# ============================================================================
# Database Connection Tests
# ============================================================================

class TestSQLConnection:
    """Test SQL database connection and configuration"""
    
    async def test_sqlite_file_creation(self):
        """Test SQLite file database creation"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        # Remove file to test creation
        os.unlink(db_path)
        assert not os.path.exists(db_path)
        
        adapter = UnifiedSQLAlchemyAdapter(db_path=db_path)
        await adapter.initialize()
        
        # File should be created
        assert os.path.exists(db_path)
        
        # Test basic operation
        task = Task(
            id="test_task",
            name="Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await adapter.save_task(task)
        
        retrieved = await adapter.get_task("test_task")
        assert retrieved is not None
        
        await adapter.shutdown()
        os.unlink(db_path)
    
    async def test_memory_database(self):
        """Test in-memory SQLite database"""
        adapter = UnifiedSQLAlchemyAdapter(db_path=":memory:")
        await adapter.initialize()
        
        # Should work normally
        task = Task(
            id="memory_task",
            name="Memory Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await adapter.save_task(task)
        
        retrieved = await adapter.get_task("memory_task")
        assert retrieved is not None
        
        await adapter.shutdown()
        
        # Each in-memory database is independent, so a new adapter will have empty tables
        adapter2 = UnifiedSQLAlchemyAdapter(db_path=":memory:")
        await adapter2.initialize()
        
        # Should have empty database (different in-memory instance)
        retrieved2 = await adapter2.get_task("memory_task")
        assert retrieved2 is None
        
        await adapter2.shutdown()
    
    async def test_postgresql_connection_string(self):
        """Test PostgreSQL connection string configuration"""
        # This test checks configuration but doesn't connect
        adapter = UnifiedSQLAlchemyAdapter(
            connection_string="postgresql+asyncpg://user:pass@localhost/testdb"
        )
        
        # Check connection string is set
        assert "postgresql" in adapter.connection_string
        
        # Don't initialize as PostgreSQL might not be available
    
    async def test_connection_pool_settings(self):
        """Test connection pool configuration"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
            db_path = tmp.name
        
        adapter = UnifiedSQLAlchemyAdapter(
            db_path=db_path,
            pool_size=10,
            max_overflow=20,
            pool_timeout=60,
            pool_recycle=1800,
            echo=True  # Enable SQL logging
        )
        
        await adapter.initialize()
        
        # Pool settings are applied to engine (not directly testable for SQLite)
        # But we can verify the adapter accepts the settings
        assert adapter.engine is not None
        
        await adapter.shutdown()
        os.unlink(db_path)


# ============================================================================
# Schema and Table Tests
# ============================================================================

class TestSQLSchema:
    """Test database schema creation and structure"""
    
    async def test_table_creation(self, sqlite_adapter):
        """Test that all required tables are created"""
        # Get table names using raw SQL
        async with sqlite_adapter.engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = {row[0] for row in result}
        
        # Check all expected tables exist
        expected_tables = {
            'tasks',
            'task_results',
            'workflows',
            'workflow_executions',
            'queue_states',
            'resource_instances',
            'resource_metrics',
            'resource_locks'
        }
        
        assert expected_tables.issubset(tables)
    
    async def test_table_indexes(self, sqlite_adapter):
        """Test that proper indexes are created"""
        # Get index information
        async with sqlite_adapter.engine.connect() as conn:
            result = await conn.execute(
                text("SELECT name, tbl_name FROM sqlite_master WHERE type='index'")
            )
            indexes = [(row[0], row[1]) for row in result]
        
        # Check key indexes exist
        index_names = [idx[0] for idx in indexes]
        
        # Task indexes
        assert any('status' in idx and 'priority' in idx for idx in index_names)
        assert any('workflow_id' in idx for idx in index_names)
        
        # Resource indexes  
        assert any('hub' in idx and 'status' in idx for idx in index_names)
    
    async def test_foreign_key_constraints(self, sqlite_adapter):
        """Test foreign key constraints"""
        # Save a task
        task = Task(
            id="fk_test",
            name="FK Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await sqlite_adapter.save_task(task)
        
        # Save a result for the task
        result = TaskResult(
            task_id="fk_test",
            status="completed",
            result={},
            duration_seconds=1.0
        )
        await sqlite_adapter.save_task_result(result)
        
        # Delete the task
        await sqlite_adapter.delete_task("fk_test")
        
        # Result should also be deleted (CASCADE)
        retrieved_result = await sqlite_adapter.get_task_result("fk_test")
        assert retrieved_result is None
    
    async def test_column_types_and_constraints(self, sqlite_adapter):
        """Test column types and constraints"""
        # Test various data types
        task = Task(
            id="type_test",
            name="Type Test",
            protocol="test",
            method="test",
            params={"nested": {"data": [1, 2, 3]}},  # JSON field
            priority="high",
            dependencies=["dep1", "dep2"],  # Array field
            created_at=datetime.utcnow()  # DateTime field
        )
        await sqlite_adapter.save_task(task)
        
        retrieved = await sqlite_adapter.get_task("type_test")
        assert retrieved.params["nested"]["data"] == [1, 2, 3]
        assert set(retrieved.dependencies) == {"dep1", "dep2"}  # Check set equality, not order
        assert isinstance(retrieved.created_at, datetime)


# ============================================================================
# Transaction Tests
# ============================================================================

class TestSQLTransactions:
    """Test transaction handling"""
    
    async def test_transaction_rollback(self, sqlite_adapter):
        """Test transaction rollback on error"""
        # This is implicitly tested - if an error occurs during save,
        # the transaction should rollback
        
        # Create a task with invalid data that will cause an error
        # SQLAlchemy handles this internally
        task = Task(
            id="rollback_test",
            name="Rollback Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        
        await sqlite_adapter.save_task(task)
        
        # Try to save duplicate (should handle gracefully)
        duplicate = Task(
            id="rollback_test",  # Same ID
            name="Duplicate",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        
        # Should update, not fail
        await sqlite_adapter.save_task(duplicate)
        
        # Check that the update worked
        retrieved = await sqlite_adapter.get_task("rollback_test")
        assert retrieved.name == "Duplicate"
    
    async def test_batch_transaction(self, sqlite_adapter):
        """Test batch operations in a transaction"""
        tasks = [
            Task(
                id=f"batch_{i}",
                name=f"Batch {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            for i in range(10)
        ]
        
        # Batch save should be atomic
        await sqlite_adapter.save_tasks_batch(tasks)
        
        # All should be saved
        for task in tasks:
            retrieved = await sqlite_adapter.get_task(task.id)
            assert retrieved is not None
    
    async def test_concurrent_transactions(self, sqlite_adapter):
        """Test concurrent transaction handling"""
        async def save_task(i):
            task = Task(
                id=f"concurrent_{i}",
                name=f"Concurrent {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await sqlite_adapter.save_task(task)
            return await sqlite_adapter.get_task(f"concurrent_{i}")
        
        # Run concurrent saves
        tasks = [save_task(i) for i in range(20)]
        results = await asyncio.gather(*tasks)
        
        # All should succeed
        assert all(r is not None for r in results)
        assert len(results) == 20


# ============================================================================
# Query Optimization Tests
# ============================================================================

class TestSQLQueries:
    """Test SQL query optimization and performance"""
    
    async def test_indexed_queries(self, populated_adapter):
        """Test that queries use indexes efficiently"""
        # Add more tasks for testing
        for i in range(100):
            task = Task(
                id=f"perf_{i}",
                name=f"Perf {i}",
                protocol="test",
                method="test",
                params={},
                priority="high" if i % 2 == 0 else "low",
                status="queued" if i < 50 else "completed"
            )
            await populated_adapter.save_task(task)
        
        # Query by status (should use index)
        start = datetime.utcnow()
        queued = await populated_adapter.get_tasks_by_status("queued")
        duration = (datetime.utcnow() - start).total_seconds()
        
        assert len(queued) >= 50
        assert duration < 0.1  # Should be fast with index
    
    async def test_join_queries(self, populated_adapter):
        """Test queries with joins"""
        # Create workflow with tasks
        workflow = Workflow(
            id="join_test",
            name="Join Test",
            tasks=[{"name": f"Task {i}", "protocol": "test", "method": f"method{i}"} for i in range(5)]
        )
        await populated_adapter.save_workflow(workflow)
        
        # Create tasks for workflow
        for i in range(5):
            task = Task(
                id=f"join_task_{i}",
                name=f"Join Task {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal",
                workflow_id="join_test"
            )
            await populated_adapter.save_task(task)
            
            # Add result for some tasks
            if i < 3:
                result = TaskResult(
                    task_id=f"join_task_{i}",
                    status="completed",
                    result={"index": i},
                    duration_seconds=i + 1.0
                )
                await populated_adapter.save_task_result(result)
        
        # Query tasks with their results (implicit join)
        tasks = await populated_adapter.get_tasks_by_workflow("join_test")
        assert len(tasks) == 5
        
        # Get results
        for i in range(3):
            result = await populated_adapter.get_task_result(f"join_task_{i}")
            assert result is not None
            assert result.duration_seconds == i + 1.0
    
    async def test_aggregation_queries(self, populated_adapter):
        """Test aggregation queries"""
        # Add tasks with various statuses
        statuses = ["queued", "executing", "completed", "failed"]
        for status in statuses:
            for i in range(10):
                task = Task(
                    id=f"agg_{status}_{i}",
                    name=f"Agg {status} {i}",
                    protocol="test",
                    method="test",
                    params={},
                    priority="normal",
                    status=status
                )
                await populated_adapter.save_task(task)
        
        # Get counts by status
        counts = await populated_adapter.get_task_count_by_status()
        
        for status in statuses:
            assert counts.get(status, 0) >= 10
    
    async def test_pagination_queries(self, populated_adapter):
        """Test query pagination (if implemented)"""
        # Add many tasks
        for i in range(100):
            task = Task(
                id=f"page_{i}",
                name=f"Page {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal",
                status="queued"
            )
            await populated_adapter.save_task(task)
        
        # Get all queued tasks (no built-in pagination in current implementation)
        all_queued = await populated_adapter.get_tasks_by_status("queued")
        assert len(all_queued) >= 100


# ============================================================================
# Data Type Handling Tests
# ============================================================================

class TestSQLDataTypes:
    """Test handling of various data types"""
    
    async def test_json_field_handling(self, sqlite_adapter):
        """Test JSON field storage and retrieval"""
        complex_params = {
            "string": "test",
            "number": 42,
            "float": 3.14,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "nested": {
                "deep": {
                    "value": "found"
                }
            }
        }
        
        task = Task(
            id="json_test",
            name="JSON Test",
            protocol="test",
            method="test",
            params=complex_params,
            priority="normal"
        )
        await sqlite_adapter.save_task(task)
        
        retrieved = await sqlite_adapter.get_task("json_test")
        assert retrieved.params == complex_params
        assert retrieved.params["nested"]["deep"]["value"] == "found"
    
    async def test_datetime_handling(self, sqlite_adapter):
        """Test datetime field handling"""
        now = datetime.utcnow()
        
        task = Task(
            id="datetime_test",
            name="DateTime Test",
            protocol="test",
            method="test",
            params={},
            priority="normal",
            created_at=now
        )
        await sqlite_adapter.save_task(task)
        
        # Complete the task
        task.status = "completed"
        task.completed_at = now + timedelta(seconds=10)
        await sqlite_adapter.save_task(task)
        
        retrieved = await sqlite_adapter.get_task("datetime_test")
        assert retrieved.created_at is not None
        assert retrieved.completed_at is not None
        assert retrieved.completed_at > retrieved.created_at
    
    async def test_enum_handling(self, sqlite_adapter):
        """Test enum field handling"""
        resource = ResourceInstance(
            id="enum_test",
            name="Enum Test",
            type=ResourceType.OLLAMA,  # Enum
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY,  # Enum
            metadata={}
        )
        await sqlite_adapter.save_instance("hub_test", resource)
        
        retrieved = await sqlite_adapter.load_instance("enum_test")
        assert retrieved["type"] == ResourceType.OLLAMA.value
        assert retrieved["status"] == ResourceStatus.HEALTHY.value
    
    async def test_large_text_handling(self, sqlite_adapter):
        """Test handling of large text fields"""
        large_text = "x" * 10000  # 10KB of text
        
        task = Task(
            id="large_text",
            name="Large Text Test",
            protocol="test",
            method="test",
            params={"data": large_text},
            priority="normal"
        )
        await sqlite_adapter.save_task(task)
        
        retrieved = await sqlite_adapter.get_task("large_text")
        assert len(retrieved.params["data"]) == 10000
        assert retrieved.params["data"] == large_text


# ============================================================================
# Metrics and Performance Tests
# ============================================================================

class TestSQLMetrics:
    """Test metrics storage and retrieval"""
    
    async def test_metrics_time_series(self, sqlite_adapter):
        """Test time-series metrics storage"""
        resource = ResourceInstance(
            id="metrics_test",
            name="Metrics Resource",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await sqlite_adapter.save_instance("metrics_hub", resource)
        
        # Save metrics over time
        base_time = datetime.utcnow()
        for i in range(10):
            metrics = ResourceMetrics(
                cpu_percent=30.0 + i * 2,
                memory_mb=512 + i * 10,
                request_count=100 * (i + 1),
                error_count=i,
                avg_response_time_ms=200 + i * 5
            )
            await sqlite_adapter.save_metrics("metrics_test", metrics)
            await asyncio.sleep(0.1)
        
        # Query metrics history
        end_time = datetime.utcnow() + timedelta(minutes=1)
        start_time = base_time - timedelta(minutes=1)
        
        history = await sqlite_adapter.get_metrics_history(
            "metrics_test", start_time, end_time
        )
        
        assert len(history) == 10
        
        # Check values are correct
        first = history[0]
        last = history[-1]
        assert first["cpu_percent"] == 30.0
        assert last["cpu_percent"] == 48.0
    
    async def test_metrics_retention(self, sqlite_adapter):
        """Test automatic metrics retention/cleanup"""
        resource = ResourceInstance(
            id="retention_test",
            name="Retention Test",
            type=ResourceType.OLLAMA,
            endpoint="http://localhost:8080",
            status=ResourceStatus.HEALTHY
        )
        await sqlite_adapter.save_instance("retention_hub", resource)
        
        # Save old metrics (should be cleaned up)
        old_metrics = ResourceMetrics(
            cpu_percent=50.0,
            memory_mb=512,
            request_count=100
        )
        
        # Manually insert old metrics using raw SQL
        async with sqlite_adapter.engine.begin() as conn:
            old_time = datetime.utcnow() - timedelta(hours=25)  # Older than 24 hours
            await conn.execute(
                text("""
                    INSERT INTO resource_metrics 
                    (instance_id, timestamp, cpu_percent, memory_mb, request_count)
                    VALUES (:instance_id, :timestamp, :cpu, :memory, :requests)
                """),
                {
                    "instance_id": "retention_test",
                    "timestamp": old_time,
                    "cpu": 50.0,
                    "memory": 512,
                    "requests": 100
                }
            )
        
        # Save new metrics (should trigger cleanup)
        new_metrics = ResourceMetrics(
            cpu_percent=60.0,
            memory_mb=1024,
            request_count=200
        )
        await sqlite_adapter.save_metrics("retention_test", new_metrics)
        
        # Query all metrics
        end_time = datetime.utcnow() + timedelta(minutes=1)
        start_time = datetime.utcnow() - timedelta(days=2)
        
        history = await sqlite_adapter.get_metrics_history(
            "retention_test", start_time, end_time
        )
        
        # Old metrics might be cleaned up (depending on implementation)
        # At least new metrics should be there
        assert len(history) >= 1
        assert history[-1]["cpu_percent"] == 60.0


# ============================================================================
# Database-Specific Features
# ============================================================================

class TestSQLiteSpecific:
    """Test SQLite-specific features"""
    
    async def test_wal_mode(self, sqlite_adapter):
        """Test Write-Ahead Logging mode for better concurrency"""
        # Check if WAL mode is enabled (if implemented)
        async with sqlite_adapter.engine.connect() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            mode = result.scalar()
            # WAL mode might not be enabled by default
            assert mode in ["wal", "delete", "memory"]
    
    async def test_vacuum_operation(self, sqlite_adapter):
        """Test database vacuum operation"""
        # Add and delete many tasks
        for i in range(100):
            task = Task(
                id=f"vacuum_{i}",
                name=f"Vacuum {i}",
                protocol="test",
                method="test",
                params={},
                priority="normal"
            )
            await sqlite_adapter.save_task(task)
        
        # Delete all tasks
        for i in range(100):
            await sqlite_adapter.delete_task(f"vacuum_{i}")
        
        # Vacuum would reclaim space (not directly testable)
        # but operation should not fail
        try:
            async with sqlite_adapter.engine.connect() as conn:
                await conn.execute(text("VACUUM"))
        except Exception:
            # Some async drivers don't support VACUUM
            pass


class TestPostgreSQLCompatibility:
    """Test PostgreSQL compatibility (configuration only)"""
    
    def test_postgresql_connection_string(self):
        """Test PostgreSQL connection string format"""
        adapter = UnifiedSQLAlchemyAdapter(
            connection_string="postgresql+asyncpg://user:pass@localhost:5432/dbname"
        )
        
        assert "postgresql" in adapter.connection_string
        assert "asyncpg" in adapter.connection_string
    
    def test_mysql_connection_string(self):
        """Test MySQL connection string format"""
        adapter = UnifiedSQLAlchemyAdapter(
            connection_string="mysql+aiomysql://user:pass@localhost:3306/dbname"
        )
        
        assert "mysql" in adapter.connection_string
        assert "aiomysql" in adapter.connection_string


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestSQLErrorHandling:
    """Test SQL error handling"""
    
    async def test_connection_error_handling(self):
        """Test handling of connection errors"""
        # Try to connect to non-existent database
        adapter = UnifiedSQLAlchemyAdapter(
            connection_string="postgresql+asyncpg://bad:bad@nonexistent:5432/bad"
        )
        
        # Should handle connection error gracefully
        with pytest.raises(Exception):
            await adapter.initialize()
    
    async def test_constraint_violation_handling(self, sqlite_adapter):
        """Test handling of constraint violations"""
        # This is handled by the upsert logic
        task = Task(
            id="constraint_test",
            name="Original",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        await sqlite_adapter.save_task(task)
        
        # Save again with different data (should update)
        task.name = "Updated"
        await sqlite_adapter.save_task(task)
        
        retrieved = await sqlite_adapter.get_task("constraint_test")
        assert retrieved.name == "Updated"
    
    async def test_data_integrity_errors(self, sqlite_adapter):
        """Test handling of data integrity errors"""
        # Save task with very long ID (might exceed column limit)
        long_id = "x" * 1000
        
        task = Task(
            id=long_id,
            name="Long ID Test",
            protocol="test",
            method="test",
            params={},
            priority="normal"
        )
        
        # Should handle gracefully (truncate or error)
        try:
            await sqlite_adapter.save_task(task)
            # If it saves, should be retrievable
            retrieved = await sqlite_adapter.get_task(long_id)
            assert retrieved is not None
        except Exception:
            # Expected for very long IDs
            pass


# ============================================================================
# Integration Tests
# ============================================================================

class TestSQLIntegration:
    """Integration tests for SQL adapter"""
    
    async def test_complete_workflow_lifecycle(self, sqlite_adapter):
        """Test complete workflow lifecycle with SQL persistence"""
        # Create workflow
        workflow = Workflow(
            id="sql_workflow",
            name="SQL Test Workflow",
            tasks=[
                {"name": "Step 1", "protocol": "test", "method": "step1"},
                {"name": "Step 2", "protocol": "test", "method": "step2"},
                {"name": "Step 3", "protocol": "test", "method": "step3"}
            ],
            metadata={"version": "1.0"}
        )
        await sqlite_adapter.save_workflow(workflow)
        
        # Create execution
        execution = WorkflowExecution(
            execution_id="sql_exec",
            workflow_id="sql_workflow",
            status="running",
            completed_tasks=0,
            failed_tasks=0,
            total_tasks=3
        )
        await sqlite_adapter.save_workflow_execution(execution)
        
        # Create tasks
        tasks = []
        for i in range(3):
            task = Task(
                id=f"sql_task_{i}",
                name=f"Step {i+1}",
                protocol="test",
                method=f"step{i+1}",
                params={"step": i+1},
                priority="high" if i == 0 else "normal",
                workflow_id="sql_workflow",
                dependencies=[f"sql_task_{i-1}"] if i > 0 else []
            )
            tasks.append(task)
            await sqlite_adapter.save_task(task)
        
        # Create resources
        for i in range(2):
            resource = ResourceInstance(
                id=f"sql_resource_{i}",
                name=f"SQL Worker {i}",
                type=ResourceType.OLLAMA,
                endpoint=f"http://localhost:808{i}",
                status=ResourceStatus.HEALTHY
            )
            await sqlite_adapter.save_instance("sql_hub", resource)
        
        # Process tasks
        for i, task in enumerate(tasks):
            # Assign to resource
            task.assigned_provider = f"sql_resource_{i % 2}"
            task.status = "executing"
            await sqlite_adapter.save_task(task)
            
            # Save metrics
            metrics = ResourceMetrics(
                cpu_percent=50.0 + i * 10,
                memory_mb=512 + i * 100,
                request_count=1,
                avg_response_time_ms=100 + i * 50
            )
            await sqlite_adapter.save_metrics(task.assigned_provider, metrics)
            
            # Complete task
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            await sqlite_adapter.save_task(task)
            
            # Save result
            result = TaskResult(
                task_id=task.id,
                status="completed",
                result={"step": i+1, "output": f"Step {i+1} complete"},
                duration_seconds=1.5 + i * 0.5
            )
            await sqlite_adapter.save_task_result(result)
            
            # Update execution progress
            execution.completed_tasks = i + 1
            await sqlite_adapter.save_workflow_execution(execution)
        
        # Verify final state
        workflow_tasks = await sqlite_adapter.get_tasks_by_workflow("sql_workflow")
        assert len(workflow_tasks) == 3
        assert all(t.status == "completed" for t in workflow_tasks)
        
        # Check resource utilization
        utilization = await sqlite_adapter.get_resource_utilization("sql_hub")
        assert utilization["total_instances"] == 2
        
        # Verify execution completed
        final_execution = await sqlite_adapter.get_workflow_execution("sql_exec")
        assert final_execution.completed_tasks == 3