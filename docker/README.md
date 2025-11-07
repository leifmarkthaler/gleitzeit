# Docker Files Directory

This directory contains all Docker-related files for the Gleitzeit project.

## Files

### Dockerfiles
- **Dockerfile.api** - API server container
- **Dockerfile.base** - Base image with common dependencies
- **Dockerfile.ui** - UI server container  
- **Dockerfile.worker** - Worker container for task execution

### Docker Compose Files
- **docker-compose.yml** - Main compose file
- **docker-compose.dev.yml** - Development environment
- **docker-compose.prod.yml** - Production environment
- **docker-compose.observability.yml** - Observability stack (Grafana, Loki, etc.)

## CLI Integration

The Gleitzeit CLI automatically references these files from the `docker/` directory:

### Updated Files:
- ✅ `src/gleitzeit/cli/serve_docker.py` - Generates and uses docker-compose files
  - Copies Dockerfiles to `docker/` directory
  - References `docker/Dockerfile.api`, `docker/Dockerfile.ui`, `docker/Dockerfile.worker`
  
- ✅ `src/gleitzeit/cli/stop_command.py` - Stops Docker containers
  - Looks for compose files in `docker/` directory and root
  
### Files That Reference docker-compose (No Changes Needed):
These files reference `docker-compose` as a command or generated files, not the static files:
- `src/gleitzeit/cli/scale_command.py` - Uses generated `docker-compose-proper.yml`
- `src/gleitzeit/cli/clean_command.py` - Uses generated `docker-compose-proper.yml`
- `src/gleitzeit/cli/logs_command.py` - Uses generated `docker-compose-proper.yml`
- `src/gleitzeit/cli/mode_utils.py` - Uses generated `docker-compose-proper.yml`
- `src/gleitzeit/cli/serve_unified.py` - Checks for docker-compose command availability

## Usage

### Start Services with Docker
```bash
gleitzeit serve --docker
```

### Stop Services
```bash
gleitzeit stop --force --all
```

### Scale Workers
```bash
gleitzeit scale task_execution --count 3
```

### View Logs
```bash
gleitzeit logs --follow
```

## Notes

- The CLI generates dynamic compose files (e.g., `docker-compose-gleitzeit.yml`) in the project root during runtime
- Static compose files in this directory are templates and references
- All Dockerfiles use the project root as build context with `context: .`
