# Test Strategy for Gleitzeit v0.0.5 Release

## Pre-Release Testing Checklist

### 🔴 Critical - Must Fix Before Release

#### 1. Fix Deprecation Warnings
**Priority: HIGH | Effort: LOW | Time: 1-2 hours**

- [ ] Update Pydantic v2 deprecated methods
  ```python
  # Find and replace in all files:
  .dict() → .model_dump()
  .json() → .model_dump_json()
  min_items → min_length
  json_encoders → Use @field_serializer instead
  ```
  
- [ ] Fix SQLAlchemy 2.0 deprecations
  ```python
  # In unified_sqlalchemy.py:
  from sqlalchemy.ext.declarative import declarative_base
  → from sqlalchemy.orm import declarative_base
  ```

- [ ] Run tests to verify fixes:
  ```bash
  pytest tests/persistence/ -W error::DeprecationWarning
  ```

#### 2. Fix SQL Adapter Connection Issues
**Priority: HIGH | Effort: MEDIUM | Time: 2-3 hours**

- [ ] Fix SQLAlchemy async session handling
- [ ] Test with both SQLite and PostgreSQL
- [ ] Ensure connection pool settings work
- [ ] Run SQL adapter tests:
  ```bash
  pytest tests/persistence/test_sql_adapter.py -v
  pytest tests/persistence/test_unified_persistence.py -k sql -v
  ```

#### 3. Stabilize Core Workflow Tests
**Priority: HIGH | Effort: MEDIUM | Time: 3-4 hours**

- [ ] Mock Ollama provider for tests
- [ ] Fix parameter validation in workflows
- [ ] Ensure all provider dependencies are properly mocked
- [ ] Run workflow tests:
  ```bash
  # Create test fixtures
  pytest tests/workflows/test_simple_llm_workflow.py -v
  pytest tests/workflows/test_mixed_workflow.py -v
  pytest tests/workflows/test_batch_workflows.py -v
  ```

### 🟡 Important - Should Fix Before Release

#### 4. Update Test Dependencies
**Priority: MEDIUM | Effort: LOW | Time: 1 hour**

- [ ] Ensure all test dependencies are in requirements-dev.txt
- [ ] Add pytest-cov to pyproject.toml dev dependencies
- [ ] Update GitHub Actions workflow for CI
- [ ] Verify test environment setup:
  ```bash
  pip install -e ".[dev]"
  pytest --version
  coverage --version
  ```

#### 5. Add Integration Test Suite
**Priority: MEDIUM | Effort: HIGH | Time: 4-5 hours**

- [ ] Create integration test for complete workflow execution
- [ ] Test API server startup and shutdown
- [ ] Test client-server communication
- [ ] Create test file: `tests/integration/test_end_to_end.py`
  ```python
  async def test_complete_workflow_execution():
      # Start with workflow YAML
      # Execute through client
      # Verify all tasks complete
      # Check persistence
  ```

### 🟢 Nice to Have - Can Do Post-Release

#### 6. Add CLI Testing
**Priority: LOW | Effort: MEDIUM | Time: 3-4 hours**

- [ ] Use Click's testing utilities
- [ ] Test all major CLI commands
- [ ] Create `tests/cli/test_commands.py`
  ```python
  from click.testing import CliRunner
  from gleitzeit.cli import cli
  
  def test_run_command():
      runner = CliRunner()
      result = runner.invoke(cli, ['run', 'test.yaml'])
      assert result.exit_code == 0
  ```

#### 7. Improve Execution Engine Coverage
**Priority: LOW | Effort: HIGH | Time: 5-6 hours**

- [ ] Add tests for task scheduling
- [ ] Test dependency resolution
- [ ] Test failure handling and retries
- [ ] Test parallel execution

## Testing Environments

### Local Development Testing
```bash
# 1. Clean install
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Run quick smoke tests
pytest tests/unit/core/test_models.py -v  # Should pass quickly
pytest tests/persistence/test_memory_adapter.py -v  # No external deps

# 3. Run full test suite
pytest tests/ -v --tb=short
```

### Docker Testing Environment
```bash
# Create test container
docker build -t gleitzeit-test .
docker run -it gleitzeit-test pytest

# Test with external services
docker-compose -f docker-compose.test.yml up
```

### Manual Testing Scenarios

#### Scenario 1: Basic LLM Workflow
```bash
# Start Ollama
ollama serve

# Create test workflow
cat > test_basic.yaml << EOF
name: "Basic Test"
tasks:
  - id: "hello"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Say hello"
EOF

# Run workflow
gleitzeit run test_basic.yaml
```

#### Scenario 2: Python Execution
```bash
# Create Python script
cat > test_script.py << EOF
def main():
    return {"result": "success", "value": 42}
EOF

# Create workflow
cat > test_python.yaml << EOF
name: "Python Test"
tasks:
  - id: "execute"
    method: "python/execute"
    parameters:
      script: "test_script.py"
EOF

# Run workflow
gleitzeit run test_python.yaml
```

#### Scenario 3: Batch Processing
```bash
# Create test files
mkdir test_docs
echo "Test content 1" > test_docs/file1.txt
echo "Test content 2" > test_docs/file2.txt

# Run batch processing
gleitzeit batch test_docs --pattern "*.txt" --prompt "Summarize"
```

#### Scenario 4: API Mode
```bash
# Terminal 1: Start server
gleitzeit serve --port 8000

# Terminal 2: Test client
python << EOF
import asyncio
from gleitzeit import GleitzeitClient

async def test():
    async with GleitzeitClient(mode="api", api_port=8000) as client:
        result = await client.chat("Hello", model="llama3.2")
        print(result)

asyncio.run(test())
EOF
```

## Performance Testing

### Load Testing
```python
# tests/performance/test_load.py
import asyncio
import time
from gleitzeit import GleitzeitClient

async def load_test(num_requests=100):
    async with GleitzeitClient() as client:
        start = time.time()
        tasks = []
        for i in range(num_requests):
            task = client.execute_task({
                "method": "mcp/tool.echo",
                "parameters": {"message": f"Test {i}"}
            })
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start
        
        print(f"Processed {num_requests} requests in {elapsed:.2f}s")
        print(f"Throughput: {num_requests/elapsed:.2f} req/s")
        
        return results

# Run with different loads
asyncio.run(load_test(10))    # Smoke test
asyncio.run(load_test(100))   # Normal load
asyncio.run(load_test(1000))  # Stress test
```

### Memory Leak Testing
```bash
# Monitor memory usage during long-running test
mprof run python tests/performance/test_memory_leak.py
mprof plot
```

## Regression Testing

### Version Compatibility
- [ ] Test upgrade from v0.0.4 to v0.0.5
- [ ] Verify workflow YAML compatibility
- [ ] Check persistence migration
- [ ] Test API compatibility

### Backward Compatibility Checklist
- [ ] Old workflow files still work
- [ ] Client API maintains same interface
- [ ] CLI commands unchanged
- [ ] Configuration files compatible

## Test Coverage Goals

### Minimum Coverage for v0.0.5
- Core models: >80% ✅
- Persistence: >70% ✅
- Providers: >60% ✅
- Overall: >50% ⚠️ (currently ~40%)

### Target Coverage for v1.0
- Core: >90%
- Persistence: >85%
- API: >80%
- CLI: >70%
- Overall: >75%

## CI/CD Pipeline

### GitHub Actions Workflow
```yaml
# .github/workflows/test.yml
name: Test Suite

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: [3.8, 3.9, 3.10, 3.11]
    
    steps:
    - uses: actions/checkout@v2
    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: ${{ matrix.python-version }}
    
    - name: Install dependencies
      run: |
        pip install -e ".[dev]"
    
    - name: Run tests
      run: |
        pytest tests/ --cov=src/gleitzeit --cov-report=xml
    
    - name: Upload coverage
      uses: codecov/codecov-action@v2
```

## Release Testing Protocol

### Day Before Release
1. [ ] Run full test suite on clean environment
2. [ ] Test installation from git
3. [ ] Test all example workflows
4. [ ] Review all deprecation warnings
5. [ ] Check documentation examples

### Release Day
1. [ ] Tag release candidate: `v0.0.5-rc1`
2. [ ] Test PyPI package installation
3. [ ] Run smoke tests on installed package
4. [ ] Test upgrade from previous version
5. [ ] Final manual testing of key features

### Post-Release
1. [ ] Monitor GitHub issues for bug reports
2. [ ] Test in production-like environment
3. [ ] Gather performance metrics
4. [ ] Plan patches if needed

## Test Documentation

### Update Test README
```markdown
# tests/README.md

## Running Tests

### Quick Start
```bash
pytest tests/unit/  # Fast unit tests
pytest tests/persistence/  # Persistence tests
pytest tests/ -m "not slow"  # Skip slow tests
```

### With Coverage
```bash
pytest --cov=src/gleitzeit --cov-report=html
open htmlcov/index.html
```

### Test Markers
- `@pytest.mark.slow` - Long-running tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.requires_ollama` - Needs Ollama running
- `@pytest.mark.requires_redis` - Needs Redis running
```

## Risk Assessment

### High Risk Areas
1. **Persistence Layer** - Data loss/corruption
   - Mitigation: Extensive testing, backups
2. **Workflow Execution** - Task failures
   - Mitigation: Retry logic, error handling
3. **Resource Management** - Memory leaks
   - Mitigation: Load testing, monitoring

### Medium Risk Areas
1. **API Compatibility** - Breaking changes
   - Mitigation: Version checking, deprecation warnings
2. **Provider Integration** - External service failures
   - Mitigation: Mocking, timeout handling

### Low Risk Areas
1. **CLI Interface** - User experience issues
   - Mitigation: Manual testing, user feedback
2. **Documentation** - Outdated examples
   - Mitigation: Automated example testing

## Success Criteria for v0.0.5

### Must Have
- [x] All critical tests passing
- [x] No data corruption issues
- [x] Core functionality working
- [ ] Deprecation warnings resolved
- [ ] SQL adapter functional

### Should Have
- [ ] >50% test coverage
- [ ] Integration tests passing
- [ ] Performance benchmarks established
- [ ] CI/CD pipeline running

### Nice to Have
- [ ] >70% test coverage
- [ ] CLI tests implemented
- [ ] Load testing completed
- [ ] Mutation testing setup

## Timeline

### Week 1 (Pre-Release)
- Day 1-2: Fix critical issues (deprecations, SQL adapter)
- Day 3-4: Stabilize workflow tests
- Day 5: Integration testing
- Day 6-7: Manual testing and documentation

### Release Day
- Morning: Final test run
- Afternoon: Tag and release
- Evening: Monitor for issues

### Week 2 (Post-Release)
- Monitor user feedback
- Fix any critical bugs
- Plan v0.0.6 improvements

## Notes

- Focus on stability over features for v0.0.5
- Document all known issues in CHANGELOG
- Create GitHub issues for post-release improvements
- Consider beta testing with select users first

---

**Last Updated**: Before v0.0.5 release
**Owner**: Development Team
**Review**: Before each release