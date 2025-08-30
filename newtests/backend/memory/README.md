# Memory Backend Test Suite

Comprehensive test coverage for the Gleitzeit memory persistence backend.

## Test Coverage

### ✅ All 48 tests passing

The test suite covers:

1. **Initialization & Lifecycle (4 tests)**
   - Memory adapter initialization
   - Double initialization safety
   - Proper shutdown and cleanup
   - Event storage initialization

2. **Task Operations (6 tests)**
   - CRUD operations
   - Batch operations
   - Workflow ID validation
   - Reference sharing behavior (in-memory specific)

3. **Task Status & Queries (4 tests)**
   - Status filtering
   - Workflow task queries
   - Queued tasks retrieval
   - Status count statistics

4. **Workflow Operations (4 tests)**
   - Workflow CRUD
   - Status updates
   - Cascading deletion
   - Orphan task handling
   - Workflow listing with filters

5. **Task Results (2 tests)**
   - Result storage
   - Error handling

6. **Workflow Execution (1 test)**
   - Execution state tracking

7. **Queue State (3 tests)**
   - State persistence
   - Cleanup operations

8. **Locking (4 tests)**
   - Lock acquisition/release
   - Exclusive access
   - Lock expiration
   - Lock extension

9. **Resource Hub (3 tests)**
   - Instance management
   - Hub association
   - Instance deletion

10. **Metrics (2 tests)**
    - Metrics storage
    - Time-ordered retrieval

11. **Memory-Specific Features (3 tests)**
    - Data type isolation
    - Event storage limits
    - Old data cleanup

12. **Event Adapter (4 tests)**
    - Event-driven adapter initialization
    - Event emission
    - Status change events
    - Workflow completion checking

13. **Error Handling (3 tests)**
    - Operations without initialization
    - Concurrent modifications
    - Large dataset handling

14. **Integration (1 test)**
    - Complete workflow lifecycle

15. **Performance (2 tests)**
    - Bulk operations
    - Concurrent access

## Key Features Tested

### Memory-Specific Characteristics
- **Reference Sharing**: Tests verify that in-memory storage returns references to the same objects
- **Event Storage Limits**: Tests deque maxlen behavior for automatic event trimming
- **Fast Operations**: Performance tests verify sub-second response times for large datasets

### Event-Driven Architecture
- **Event Emission**: Tests event publishing to in-memory queues
- **Status Change Events**: Verifies events are emitted on task status transitions
- **Workflow Completion**: Tests atomic workflow completion checking with locking

### Locking Mechanisms
- **Simple Locking**: Tests in-memory lock acquisition and release
- **Lock Expiration**: Verifies time-based lock expiration
- **Atomic Operations**: Tests prevention of race conditions

## Running Tests

```bash
# Run all memory backend tests
python -m pytest newtests/backend/memory/test_memory_backend.py -v

# Run specific test class
python -m pytest newtests/backend/memory/test_memory_backend.py::TestTaskOperations -v

# Run event adapter tests
python -m pytest newtests/backend/memory/test_memory_backend.py::TestEventAdapter -v

# Run with coverage
python -m pytest newtests/backend/memory/test_memory_backend.py --cov=src/gleitzeit/persistence/unified_persistence --cov=src/gleitzeit/persistence/unified_memory_events
```

## Test Configuration

- Uses in-memory storage (no external dependencies)
- Automatic cleanup after each test via fixtures
- Tests both base memory adapter and event-enhanced adapter

## Requirements

- Python packages: pytest, pytest-asyncio
- No external dependencies (Redis, databases, etc.)

## Performance Characteristics

Memory backend tests demonstrate:
- **Bulk Operations**: 10,000 tasks saved in < 1 second
- **Query Performance**: Status filtering in < 0.5 seconds
- **Concurrent Access**: 1,000 concurrent operations complete successfully

## Notes

- Memory backend provides reference sharing (not copies) for performance
- Event storage automatically trims to last 10,000 events via deque maxlen
- All operations are synchronous at the storage level (async wrappers for consistency)