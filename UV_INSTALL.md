# UV Installation Guide

## Installing with UV Package Manager

### 1. Install UV
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Via pip
pip install uv
```

### 2. Install Gleitzeit

#### Development Installation
```bash
# Clone and install in development mode
git clone https://github.com/leifmarkthaler/gleitzeit
cd gleitzeit

# Install with all features
uv pip install -e ".[all]" && ~/.venv/bin/gleitzeit-setup

# Install with monitoring only
uv pip install -e ".[monitor]" && ~/.venv/bin/gleitzeit-setup

# Basic installation
uv pip install -e . && ~/.venv/bin/gleitzeit-setup
```

#### PATH Configuration
```bash
# PATH setup is handled automatically during installation
# The installer detects your shell and adds the UV bin directory to PATH

# If automatic setup failed, run manually:
gleitzeit-setup

# Or configure manually:
echo 'export PATH="$HOME/.venv/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Alternative: Use full path
~/.venv/bin/gleitzeit --help
```

#### Production Install
```bash
# Install from PyPI (when published)
uv pip install gleitzeit-cluster

# With monitoring
uv pip install "gleitzeit-cluster[monitor]"

# With all features
uv pip install "gleitzeit-cluster[all]"
```

### 3. Verify Installation
```bash
# Test installation
python test_install.py

# Check CLI
gleitzeit --help
gleitzeit version

# Quick start
gleitzeit dev      # Start development environment
gleitzeit pro      # Professional monitoring (in new terminal)
```

## UV Advantages

- 10-100x faster than pip
- Deterministic installs with lock files
- Better dependency resolution 
- Clean virtual environments

## Installation Options

### Core Features Only
```bash
uv pip install gleitzeit-cluster
```
**Includes:** Workflow orchestration, task execution, basic CLI

### With Monitoring
```bash
uv pip install "gleitzeit-cluster[monitor]"
```
**Adds:** Rich terminal interface, real-time charts, monitoring dashboard

### Development Installation
```bash
uv pip install "gleitzeit-cluster[dev]"
```
**Adds:** Testing tools, code quality, type checking

### All Features
```bash
uv pip install "gleitzeit-cluster[all]"
```
**Includes:** All features above + documentation tools

## Commands After Installation

```bash
# Start development environment
gleitzeit dev

# Launch monitoring dashboard
gleitzeit pro

# Execute functions  
gleitzeit run --function fibonacci --args n=10

# Check system status
gleitzeit status

# List available functions
gleitzeit functions list
```