# Comprehensive Test Plan for Gleitzeit V4

## Executive Summary
This document outlines a comprehensive testing strategy for the Gleitzeit workflow orchestration system. The plan covers unit tests, integration tests, and end-to-end tests for all major components, ensuring robust quality assurance and maintaining the system's reliability at 99% architecture consistency.

## Current Test Coverage Status

### Existing Tests (✅ Covered)
1. **Persistence Layer** (/newtests/persistence/)
   - Memory adapter
   - Redis adapter  
   - SQL adapter
   - Unified persistence with fallback chain
   - Persistence factory
   - Workflow execution with persistence

2. **Legacy Tests** (/tests/)
   - Protocol validation
   - Provider registry
   - Workflow management
   - CLI integration
   - Event system
   - Dependency resolution

### Coverage Gaps (❌ Need Testing)
Based on analysis of src/gleitzeit components vs existing tests:

1. **Core Components**
   - Batch processor
   - Retry manager
   - Error handler & formatter
   - JSONRPC implementation

2. **Hub Components**
   - OllamaHub (session pooling)
   - DockerHub
   - ResourceManager

3. **Common Components**
   - Circuit breaker
   - Load balancer
   - Health monitor
   - Metrics collector

4. **Providers**
   - Context manager lifecycle
   - Health check consistency
   - Session cleanup

## Test Suite Organization

```
/newtests/
├── unit/                    # Isolated component tests
│   ├── core/
│   │   ├── test_models.py
│   │   ├── test_events.py
│   │   ├── test_batch_processor.py
│   │   ├── test_retry_manager.py
│   │   ├── test_error_handler.py
│   │   └── test_jsonrpc.py
│   ├── providers/
│   │   ├── test_base_provider.py
│   │   ├── test_ollama_provider.py
│   │   ├── test_python_provider.py
│   │   └── test_mcp_provider.py
│   ├── hub/
│   │   ├── test_ollama_hub.py
│   │   ├── test_docker_hub.py
│   │   └── test_resource_manager.py
│   └── common/
│       ├── test_circuit_breaker.py
│       ├── test_load_balancer.py
│       ├── test_health_monitor.py
│       └── test_metrics.py
├── integration/             # Component interaction tests
│   ├── test_provider_hub_integration.py
│   ├── test_execution_persistence.py
│   ├── test_workflow_execution.py
│   └── test_session_pooling.py
├── e2e/                     # End-to-end workflow tests
│   ├── test_llm_workflows.py
│   ├── test_parallel_execution.py
│   ├── test_batch_processing.py
│   └── test_error_recovery.py
├── performance/             # Performance & load tests
│   ├── test_session_pool_performance.py
│   ├── test_concurrent_workflows.py
│   └── test_memory_usage.py
├── persistence/             # ✅ Already exists
└── conftest.py             # Shared fixtures
```

## Test Categories & Priorities

### Priority 1: Critical Path (Must Have)
Tests that ensure core functionality works correctly.

#### 1.1 Execution Engine Tests
```python
# test_execution_engine.py
- test_workflow_submission
- test_task_execution_lifecycle
- test_dependency_resolution
- test_parallel_execution
- test_error_propagation
- test_cleanup_on_failure
```

#### 1.2 Provider Tests
```python
# test_providers.py
- test_provider_initialization
- test_provider_health_check
- test_provider_execute_method
- test_provider_cleanup
- test_provider_context_manager
```

#### 1.3 Persistence Tests ✅
Already comprehensive in /newtests/persistence/

### Priority 2: Architecture Integrity (Should Have)
Tests that verify clean architecture principles.

#### 2.1 Separation of Concerns
```python
# test_architecture.py
- test_provider_has_no_resource_management
- test_hub_has_no_protocol_logic
- test_clean_dependencies
```

#### 2.2 Session Management
```python
# test_session_pooling.py
- test_connection_reuse
- test_connection_limits
- test_dns_caching
- test_session_cleanup_on_shutdown
- test_no_session_leaks
```

#### 2.3 Type Hints
```python
# test_type_consistency.py
- test_all_health_checks_return_bool
- test_context_managers_typed
- test_public_api_typed
```

### Priority 3: Resilience & Recovery (Should Have)
Tests for error handling and recovery mechanisms.

#### 3.1 Circuit Breaker
```python
# test_circuit_breaker.py
- test_circuit_opens_on_threshold
- test_circuit_closes_after_timeout
- test_half_open_state
- test_fallback_execution
```

#### 3.2 Retry Logic
```python
# test_retry_manager.py
- test_exponential_backoff
- test_max_retries_respected
- test_retry_on_transient_errors
- test_no_retry_on_permanent_errors
```

#### 3.3 Error Recovery
```python
# test_error_recovery.py
- test_task_failure_recovery
- test_workflow_partial_completion
- test_cleanup_after_crash
```

### Priority 4: Performance (Nice to Have)
Tests ensuring system meets performance requirements.

#### 4.1 Throughput Tests
```python
# test_performance.py
- test_100_concurrent_tasks
- test_session_pool_performance_gain  # Should show 2.7x improvement
- test_batch_processing_speed
```

#### 4.2 Resource Usage
```python
# test_resources.py
- test_memory_usage_stable
- test_no_connection_leaks
- test_cpu_usage_efficient
```

## Test Implementation Plan

### Phase 1: Critical Components (Week 1)
1. **Day 1-2**: Core Models & Events
   - Task lifecycle tests
   - Workflow state management
   - Event emission and handling

2. **Day 3-4**: Execution Engine
   - Workflow submission and execution
   - Task scheduling and dependencies
   - Error propagation

3. **Day 5**: Provider Base
   - Health checks
   - Context managers
   - Execute method

### Phase 2: Integration (Week 2)
1. **Day 1-2**: Provider-Hub Integration
   - Clean separation verification
   - Session management
   - Resource allocation

2. **Day 3-4**: End-to-End Workflows
   - Complete workflow execution
   - Parallel processing
   - Error scenarios

3. **Day 5**: Performance Baseline
   - Establish performance metrics
   - Session pooling verification
   - Load testing

### Phase 3: Resilience (Week 3)
1. **Day 1-2**: Circuit Breaker & Retry
   - Failure detection
   - Recovery mechanisms
   - Backoff strategies

2. **Day 3-4**: Batch Processing
   - Multi-file processing
   - Error handling in batches
   - Result aggregation

3. **Day 5**: Monitoring & Metrics
   - Health checks
   - Performance metrics
   - Alert mechanisms

## Test Data & Fixtures

### Shared Fixtures (conftest.py)
```python
@pytest.fixture
async def execution_engine():
    """Provides configured execution engine"""
    
@pytest.fixture
async def ollama_provider():
    """Provides initialized Ollama provider"""
    
@pytest.fixture
async def sample_workflow():
    """Provides test workflow"""
    
@pytest.fixture
async def mock_llm_response():
    """Provides mock LLM responses"""
```

### Test Data Sets
1. **Workflow Definitions**
   - Simple single-task workflow
   - Complex multi-dependency workflow
   - Parallel execution workflow
   - Error recovery workflow

2. **Mock Responses**
   - Successful LLM responses
   - Error responses
   - Timeout scenarios
   - Partial failures

## Testing Standards

### Code Coverage Requirements
- **Minimum Coverage**: 80% overall
- **Critical Components**: 95% (execution engine, providers)
- **New Code**: 90% coverage required

### Test Naming Convention
```python
def test_{component}_{action}_{expected_result}():
    """
    Example: test_provider_health_check_returns_bool
    """
```

### Test Documentation
Each test file should include:
```python
"""
Test module for {component}

Tests cover:
- {functionality 1}
- {functionality 2}
- {functionality 3}

Related components:
- {component 1}
- {component 2}
"""
```

### Assertion Standards
```python
# Use descriptive assertions
assert result.status == "completed", f"Expected completed, got {result.status}"

# Test specific fields
assert isinstance(provider.health_check(), bool)

# Verify cleanup
assert provider.session is None, "Session not cleaned up"
```

## Continuous Integration

### Test Execution Strategy
```yaml
# .github/workflows/test.yml
test-matrix:
  - unit-tests:      # Fast, run on every commit
      command: pytest newtests/unit -v
      timeout: 5m
  
  - integration:     # Medium speed, run on PR
      command: pytest newtests/integration -v
      timeout: 10m
  
  - e2e:            # Slow, run on merge to main
      command: pytest newtests/e2e -v
      timeout: 20m
  
  - performance:    # Run nightly
      command: pytest newtests/performance -v --benchmark
      timeout: 30m
```

### Test Markers
```python
@pytest.mark.unit          # Unit tests
@pytest.mark.integration   # Integration tests
@pytest.mark.e2e          # End-to-end tests
@pytest.mark.slow         # Long-running tests
@pytest.mark.redis        # Requires Redis
@pytest.mark.docker       # Requires Docker
```

## Success Metrics

### Coverage Metrics
- Line coverage: ≥80%
- Branch coverage: ≥75%
- Critical path coverage: ≥95%

### Performance Metrics
- Unit test suite: <30 seconds
- Integration suite: <2 minutes
- E2E suite: <5 minutes
- All tests: <10 minutes

### Quality Metrics
- Zero flaky tests
- All tests pass in CI
- Clear failure messages
- Fast feedback loop

## Mock Strategy

### Provider Mocking
```python
class MockOllamaProvider:
    async def execute(self, method, params):
        return {"response": "mocked response"}
    
    async def health_check(self):
        return True
```

### External Service Mocking
- Redis: Use fakeredis or memory adapter
- Ollama: Mock HTTP responses
- Docker: Use test containers
- File system: Use tmp directories

## Risk Mitigation

### Test Flakiness
- Use proper async/await patterns
- Add retry logic for network tests
- Use deterministic test data
- Isolate tests properly

### Performance Degradation
- Benchmark critical paths
- Monitor test execution time
- Alert on performance regression
- Profile slow tests

### Coverage Gaps
- Regular coverage reports
- Enforce coverage in CI
- Review uncovered code
- Add tests for new features

## Implementation Timeline

### Week 1: Foundation
- Set up test structure
- Create shared fixtures
- Implement unit tests for core components
- Establish CI pipeline

### Week 2: Integration
- Provider-hub integration tests
- Workflow execution tests
- Session management tests
- Performance baselines

### Week 3: Resilience
- Error handling tests
- Recovery mechanism tests
- Batch processing tests
- Monitoring tests

### Week 4: Polish
- Fix flaky tests
- Improve coverage
- Documentation
- Performance optimization

## Maintenance Plan

### Regular Tasks
- **Daily**: Review test failures in CI
- **Weekly**: Update test data and mocks
- **Monthly**: Coverage report review
- **Quarterly**: Performance baseline update

### Test Debt Management
- Track untested code in TODO.md
- Prioritize test debt in sprint planning
- Allocate 20% time for test improvements
- Regular test refactoring

## Conclusion

This comprehensive test plan ensures Gleitzeit maintains high quality and reliability through:

1. **Systematic Coverage**: All components have defined test requirements
2. **Clear Priorities**: Critical path tests implemented first
3. **Performance Validation**: Session pooling and efficiency verified
4. **Architecture Integrity**: Clean separation of concerns validated
5. **Continuous Improvement**: Regular maintenance and updates

The plan provides a roadmap to achieve and maintain excellent test coverage while ensuring the system remains performant, reliable, and maintainable.

## Next Steps

1. Create test structure in /newtests following this plan
2. Implement Priority 1 tests (Critical Path)
3. Set up CI pipeline with test matrices
4. Establish coverage reporting
5. Begin systematic implementation following the timeline

## Appendix: Test Checklist

### For Each Component
- [ ] Unit tests for public methods
- [ ] Integration tests with dependencies
- [ ] Error handling tests
- [ ] Performance benchmarks
- [ ] Type hint validation
- [ ] Documentation updated

### For Each Provider
- [ ] Initialization test
- [ ] Health check returns bool
- [ ] Execute method works
- [ ] Context manager lifecycle
- [ ] Cleanup on error
- [ ] No resource management

### For Each Hub
- [ ] Resource lifecycle management
- [ ] No protocol logic
- [ ] Session pooling works
- [ ] Cleanup on shutdown
- [ ] Error recovery

### For Each Workflow
- [ ] Single task execution
- [ ] Multi-task dependencies
- [ ] Parallel execution
- [ ] Error propagation
- [ ] Partial completion
- [ ] Result persistence