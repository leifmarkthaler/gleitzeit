# Using `gleitzeit serve` Command with Docker Support

## ✅ The Solution: Automatic Docker Detection

The `gleitzeit serve` command now automatically detects and uses Docker when available, providing a seamless experience while remaining pip-installable.

## How It Works

### 1. Automatic Detection (Default)
```bash
gleitzeit serve
```

The command will:
1. Check if Docker is installed and running
2. If Docker is available → Use Docker (reliable, no subprocess issues)
3. If Docker is not available → Fall back to native implementation (has subprocess deadlock issues)

### 2. Force Docker Mode
```bash
gleitzeit serve --force-docker
```
- Requires Docker to be installed
- Fails if Docker is not available
- Ensures you're using the reliable implementation

### 3. Force Native Mode
```bash
gleitzeit serve --force-native
```
- Uses the native ProcessOrchestrator (has subprocess deadlock bug!)
- Only use this if you absolutely need to avoid Docker
- **WARNING**: Processes will likely die due to subprocess issues

## Installation

The package remains fully pip-installable:

```bash
# Install from source
pip install -e .

# Or with uv (recommended)
uv pip install -e .
```

## Command Options

```bash
gleitzeit serve [OPTIONS]

Options:
  -c, --config-file TEXT      Config file path (default: gleitzeit.yaml)
  --api-host TEXT            API host (default: 0.0.0.0)
  --api-port INTEGER         API port (default: 8000)
  --ui-host TEXT             UI host (default: 0.0.0.0)
  --ui-port INTEGER          UI port (default: 8004)
  --dev-mode                 Enable development mode with auto-reload
  --no-ui                    Disable UI service
  --no-orchestrator          Disable orchestrator
  --restart                  Stop and restart all services
  --instance-name TEXT       Instance name for multi-instance deployments
  --instance-role TEXT       Instance role: standalone, coordinator, worker
  --port-offset INTEGER      Port offset for multi-instance
  --force-native            Force native implementation (has bugs!)
  --force-docker            Force Docker implementation
  --build                   Build Docker images before starting
  --help                    Show this message and exit
```

## Examples

### Basic Usage (Auto-Detect)
```bash
# Start with automatic Docker detection
gleitzeit serve

# Output when Docker is available:
# 🐳 Docker detected, using Docker-based implementation
# 🔨 Building Docker images...
# 🚀 Starting services with Docker...
# ✅ All services started successfully!
#    API: http://localhost:8000
#    UI:  http://localhost:8004

# Output when Docker is not available:
# ℹ️  Docker not available, using native implementation
# ⚠️  WARNING: Native implementation has subprocess deadlock issues!
#    Recommended: Install Docker for reliable operation
```

### Development Mode
```bash
# With Docker (reliable)
gleitzeit serve --dev-mode

# Custom ports
gleitzeit serve --api-port 8080 --ui-port 8081

# Without UI
gleitzeit serve --no-ui
```

### Docker-Specific Options
```bash
# Force Docker and rebuild images
gleitzeit serve --force-docker --build

# Restart all services
gleitzeit serve --restart
```

## What Happens Behind the Scenes

### When Docker is Available:

1. **Generates docker-compose-proper.yml** from your gleitzeit.yaml config
2. **Starts services** using `docker-compose up -d`
3. **Each service runs in its own container**:
   - Redis container
   - API container
   - UI container
   - Worker containers (one per worker type)
4. **Sets critical environment variable**: `REDIS_CLUSTER_NODES=redis:6379`
5. **No subprocess management issues** - Docker handles everything

### When Docker is Not Available:

1. **Falls back to ProcessOrchestrator**
2. **Warning displayed** about subprocess issues
3. **Uses subprocess.Popen** with PIPE (causes deadlock)
4. **Processes likely to die** when output buffers fill

## Docker Files Required

The following files are automatically used when Docker mode is active:

### Dockerfile.api
```dockerfile
FROM python:3.11-slim
# ... API-specific configuration
```

### Dockerfile.ui
```dockerfile
FROM python:3.11-slim
# ... UI-specific configuration
```

### Dockerfile.worker
```dockerfile
FROM python:3.11-slim
# ... Worker configuration
```

### docker-compose-proper.yml
Automatically generated from gleitzeit.yaml configuration

## Benefits of This Approach

1. **Seamless Experience**: Just run `gleitzeit serve`
2. **Pip Installable**: Package structure remains standard Python
3. **Automatic Fallback**: Works even without Docker (with warnings)
4. **No Breaking Changes**: Existing users can continue using the command
5. **Docker Benefits**: When available, get all Docker advantages:
   - No subprocess issues
   - Automatic restarts
   - Health monitoring
   - Easy scaling
   - Container isolation

## Checking Your Setup

### Check if Docker is detected:
```bash
# This will show if Docker is available
gleitzeit serve --help

# Or explicitly test
docker --version
docker ps
```

### Check service status (when using Docker):
```bash
docker-compose -f docker-compose-proper.yml ps
```

### View logs (when using Docker):
```bash
docker-compose -f docker-compose-proper.yml logs -f
```

## Troubleshooting

### Docker Not Detected
```bash
# Check Docker is installed
docker --version

# Check Docker daemon is running
docker ps

# Start Docker Desktop (macOS/Windows)
open -a Docker  # macOS
# or start Docker Desktop from Applications

# Install Docker if needed
# Visit: https://docs.docker.com/get-docker/
```

### Force Docker Mode Fails
```bash
# If --force-docker fails, ensure:
1. Docker is installed
2. Docker daemon is running
3. docker-compose is installed
```

### Native Mode Issues
```bash
# If using --force-native and processes die:
# This is the known subprocess deadlock bug
# Solution: Install Docker and remove --force-native
```

## Migration Path

For existing users:

1. **No changes required** - `gleitzeit serve` continues to work
2. **To get benefits** - Install Docker, same command now uses Docker
3. **To force old behavior** - Use `--force-native` (not recommended)

## Summary

The `gleitzeit serve` command now provides the best of both worlds:
- **With Docker**: Reliable, production-ready service management
- **Without Docker**: Falls back to native (with warnings about issues)
- **Pip installable**: Standard Python package structure maintained
- **Seamless upgrade**: Just install Docker to get benefits