# Redis Backend Test Suite

Comprehensive test coverage for the Gleitzeit Redis persistence backend.

## Test Coverage

### ✅ All 51 tests passing

The test suite covers:

1. **Connection & Lifecycle (6 tests)**
   - Redis connection initialization
   - Pub/sub setup
   - Proper shutdown
   - Error handling

2. **Task Operations (7 tests)**
   - CRUD operations
   - Batch operations 
   - Complex nested data
   - Workflow ID validation

3. **Task Status & Indexes (4 tests)**
   - Status tracking and updates
   - Workflow task indexing
   - Provider indexing
   - Status transitions

4. **Workflow Operations (4 tests)**
   - Workflow CRUD
   - Status filtering
   - Pagination

5. **Task Results (3 tests)**
   - Result storage
   - Error tracking
   - TTL/expiration

6. **Workflow Execution (2 tests)**
   - Execution state tracking
   - Error handling

7. **Queue State (3 tests)**
   - State persistence
   - Cleanup operations

8. **Distributed Locking (5 tests)**
   - Lock acquisition/release
   - Ownership validation
   - Lock extension
   - Conflict prevention

9. **Resource Hub (3 tests)**
   - Instance management
   - Hub association
   - Deletion cascades

10. **Metrics (2 tests)**
    - Time-series storage
    - Retention policies

11. **Utilities (3 tests)**
    - Statistics
    - Bulk queries
    - Data cleanup

12. **Error Handling (5 tests)**
    - Uninitialized operations
    - Malformed data
    - Concurrent modifications
    - Large datasets
    - Special characters

13. **Integration (2 tests)**
    - Complete workflow lifecycle
    - Resource hub with metrics

14. **Performance (2 tests)**
    - Bulk operations
    - Concurrent access

## Running Tests

```bash
# Run all Redis backend tests
python -m pytest newtests/backend/redis/test_redis_backend.py -v

# Run specific test class
python -m pytest newtests/backend/redis/test_redis_backend.py::TestTaskOperations -v

# Run with coverage
python -m pytest newtests/backend/redis/test_redis_backend.py --cov=src/gleitzeit/persistence/unified_redis
```

## Test Configuration

- Uses Redis DB 15 for isolation
- Automatic cleanup after each test
- Test key prefix: `test_gleitzeit`

## Requirements

- Redis server running on localhost:6379
- Python packages: pytest, pytest-asyncio, redis

## Known Issues

- Deprecation warning for `pubsub.close()` - should use `aclose()` in redis 5.0.1+