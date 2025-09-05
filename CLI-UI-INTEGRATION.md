# CLI UI Integration

## 🎨 Automatic UI Startup

The `gleitzeit serve` command now **automatically starts the Web UI** alongside the SystemManager API server.

### Default Behavior (With UI)
```bash
gleitzeit serve
# Starts:
# - SystemManager API on port 8000
# - Web UI on port 8001
# Output:
# 🚀 Starting SystemManager API server on 0.0.0.0:8000
# 🌐 Starting Web UI on port 8001
# ✨ Web UI available at http://localhost:8001
```

### Headless Mode (API Only)
```bash
gleitzeit serve --headless
# Starts:
# - SystemManager API on port 8000
# - No UI
# Output:
# 🚀 Starting SystemManager API server on 0.0.0.0:8000
# 🔧 Running in headless mode (API only)
```

### Custom Ports
```bash
gleitzeit serve --port 9000 --ui-port 9001
# Starts:
# - SystemManager API on port 9000
# - Web UI on port 9001
```

## 🖥️ Standalone UI Command

For advanced users who want to run the UI separately:

```bash
# Start API server in headless mode
gleitzeit serve --headless --port 8000

# In another terminal, start UI connected to the API
gleitzeit ui --port 8001 --api-host localhost --api-port 8000
```

## 📋 Command Summary

### `gleitzeit serve` Options
- `--host` - API server host (default: 0.0.0.0)
- `--port` - API server port (default: 8000)
- `--headless` - Run without UI (API only)
- `--ui-port` - UI port if not headless (default: 8001)

### `gleitzeit ui` Options
- `--port` - UI server port (default: 8001)
- `--api-host` - API server to connect to (default: localhost)
- `--api-port` - API server port (default: 8000)

## 🚀 Quick Start

For most users, simply run:
```bash
gleitzeit serve
```

This starts everything you need:
- SystemManager API server on port 8000
- Web UI on port 8001
- Open browser to http://localhost:8001

## 🔧 Production Deployment

For production, you might want to run components separately:

```bash
# API server on production host
gleitzeit serve --headless --host 0.0.0.0 --port 8000

# UI on separate host/container
gleitzeit ui --port 80 --api-host api.example.com --api-port 8000
```

## Benefits

1. **Simpler Getting Started** - One command starts everything
2. **Flexible Deployment** - Can still run components separately
3. **Better Developer Experience** - UI starts automatically for local development
4. **Production Ready** - Use --headless for API-only deployments