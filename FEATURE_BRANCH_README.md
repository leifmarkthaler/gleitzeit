# Feature Branch: Multi-Instance Ollama & Docker Support

## Branch: `feature/multi-instance-docker`

This branch implements:
1. **Multi-Ollama Instance Orchestration** - Load balancing across multiple Ollama servers
2. **Docker-based Python Execution** - Sandboxed code execution for security

## Status: IN DEVELOPMENT

### Key Changes
- Added `OllamaPoolManager` for multi-instance orchestration
- Added `DockerExecutor` for containerized Python execution
- Extended configuration system for new features
- Backward compatible with single-instance mode

### Testing
```bash
# Run orchestration tests
pytest tests/test_orchestration/

# Run Docker execution tests  
pytest tests/test_docker/

# Run all tests
pytest
```

### Building Docker Images
```bash
# Build sandbox image
docker build -f docker/images/sandbox.Dockerfile -t gleitzeit/sandbox:latest docker/images/

# Build data science image
docker build -f docker/images/datascience.Dockerfile -t gleitzeit/datascience:latest docker/images/
```

### Documentation
See `docs/DRAFT_MULTI_INSTANCE_DOCKER_DESIGN.md` for full design details.

### Merging Back
Once features are complete and tested:
```bash
git checkout main
git merge feature/multi-instance-docker
```
