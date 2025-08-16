#!/bin/bash

# Script to create feature branch for multi-instance and Docker support
# This preserves the current stable version while allowing new development

echo "🚀 Setting up feature branch for Multi-Instance Ollama & Docker Support"
echo "======================================================================="

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Error: Not in a git repository"
    exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  Warning: You have uncommitted changes"
    echo "Please commit or stash them before creating the feature branch"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Get current branch
CURRENT_BRANCH=$(git branch --show-current)
echo "📍 Current branch: $CURRENT_BRANCH"

# Create and checkout feature branch
FEATURE_BRANCH="feature/multi-instance-docker"
echo "🌿 Creating feature branch: $FEATURE_BRANCH"

# Check if branch already exists
if git show-ref --verify --quiet refs/heads/$FEATURE_BRANCH; then
    echo "⚠️  Branch $FEATURE_BRANCH already exists"
    read -p "Switch to existing branch? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        git checkout $FEATURE_BRANCH
    else
        exit 1
    fi
else
    git checkout -b $FEATURE_BRANCH
    echo "✅ Created and switched to $FEATURE_BRANCH"
fi

# Create feature directory structure
echo "📁 Creating feature directories..."
mkdir -p src/gleitzeit/orchestration
mkdir -p src/gleitzeit/providers/ollama_pool
mkdir -p src/gleitzeit/execution/docker
mkdir -p tests/test_orchestration
mkdir -p tests/test_docker
mkdir -p docker/images

# Create placeholder files for new components
echo "📄 Creating placeholder files..."

# Ollama Pool Manager placeholder
cat > src/gleitzeit/orchestration/__init__.py << 'EOF'
"""
Orchestration components for multi-instance support
"""
EOF

cat > src/gleitzeit/orchestration/ollama_pool.py << 'EOF'
"""
Ollama Pool Manager - Orchestrates multiple Ollama instances
"""
from typing import List, Dict, Any, Optional
import asyncio
import logging

logger = logging.getLogger(__name__)


class OllamaPoolManager:
    """
    Manages multiple Ollama instances with load balancing and failover
    """
    
    def __init__(self, instances: List[Dict[str, Any]]):
        self.instances = instances
        self.health_status = {}
        self.active_requests = {}
        
    async def initialize(self):
        """Initialize all instances and start health monitoring"""
        pass
        
    async def get_instance(self, model: str = None, strategy: str = "least_loaded") -> str:
        """Get best instance based on strategy"""
        pass
        
    async def health_check(self, instance_id: str) -> bool:
        """Check health of specific instance"""
        pass
EOF

# Docker Executor placeholder
cat > src/gleitzeit/execution/__init__.py << 'EOF'
"""
Execution environments for Python code
"""
EOF

cat > src/gleitzeit/execution/docker_executor.py << 'EOF'
"""
Docker Executor - Runs Python code in isolated containers
"""
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class DockerExecutor:
    """
    Executes Python code in Docker containers for isolation
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.container_pool = {}
        
    async def execute(
        self, 
        code: str, 
        image: str = "python:3.11-slim",
        timeout: int = 60,
        memory_limit: str = "512m"
    ) -> Dict[str, Any]:
        """Execute code in container"""
        pass
        
    async def cleanup(self):
        """Clean up idle containers"""
        pass
EOF

# Create test placeholders
cat > tests/test_orchestration/test_ollama_pool.py << 'EOF'
"""
Tests for Ollama Pool Manager
"""
import pytest
import asyncio


class TestOllamaPoolManager:
    """Test multi-instance Ollama orchestration"""
    
    @pytest.mark.asyncio
    async def test_load_balancing(self):
        """Test load balancing across instances"""
        pass
        
    @pytest.mark.asyncio
    async def test_failover(self):
        """Test automatic failover on instance failure"""
        pass
EOF

cat > tests/test_docker/test_docker_executor.py << 'EOF'
"""
Tests for Docker Executor
"""
import pytest
import asyncio


class TestDockerExecutor:
    """Test Docker-based code execution"""
    
    @pytest.mark.asyncio
    async def test_sandbox_execution(self):
        """Test code execution in sandbox"""
        pass
        
    @pytest.mark.asyncio
    async def test_resource_limits(self):
        """Test resource limit enforcement"""
        pass
EOF

# Create Docker images directory
cat > docker/images/sandbox.Dockerfile << 'EOF'
# Minimal Python sandbox for untrusted code execution
FROM python:3.11-slim

# Install only essential packages
RUN pip install --no-cache-dir \
    numpy==1.24.3 \
    pandas==2.0.3

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash sandbox

# Set up working directory
WORKDIR /workspace

# Switch to non-root user
USER sandbox

# Set Python to unbuffered mode
ENV PYTHONUNBUFFERED=1

CMD ["python"]
EOF

cat > docker/images/datascience.Dockerfile << 'EOF'
# Data science environment with common ML libraries
FROM python:3.11

# Install data science packages
RUN pip install --no-cache-dir \
    numpy==1.24.3 \
    pandas==2.0.3 \
    scikit-learn==1.3.0 \
    matplotlib==3.7.2 \
    seaborn==0.12.2 \
    jupyter==1.0.0

# Install additional ML frameworks (optional)
# RUN pip install tensorflow torch

WORKDIR /workspace

CMD ["python"]
EOF

# Create feature branch README
cat > FEATURE_BRANCH_README.md << 'EOF'
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
EOF

echo "✅ Feature branch structure created!"
echo ""
echo "📋 Next steps:"
echo "1. Review the design document: docs/DRAFT_MULTI_INSTANCE_DOCKER_DESIGN.md"
echo "2. Start implementing in: src/gleitzeit/orchestration/"
echo "3. Run tests with: pytest tests/test_orchestration/"
echo "4. Build Docker images in: docker/images/"
echo ""
echo "🌿 You are now on branch: $FEATURE_BRANCH"
echo "🔄 To switch back to $CURRENT_BRANCH: git checkout $CURRENT_BRANCH"