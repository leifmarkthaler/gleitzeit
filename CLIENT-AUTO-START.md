# Gleitzeit Client Auto-Start Documentation

## Overview

The Gleitzeit client can automatically start the server engine when it's not running, making it easier to use the client without manually managing server processes.

## Features

### Auto-Start Capability

When creating a Gleitzeit client, it can automatically:
1. Check if the server is already running
2. Start the server if needed
3. Wait for the server to be ready
4. Connect to the server

### Usage

```python
from gleitzeit.client import GleitzeitClient

# Default behavior - auto-starts server if needed
client = GleitzeitClient(
    api_host="localhost",
    api_port=8000
)
await client.initialize()  # Will auto-start server if not running

# Explicitly enable auto-start (this is the default)
client = GleitzeitClient(
    api_host="localhost",
    api_port=8000,
    auto_start_server=True
)

# Disable auto-start
client = GleitzeitClient(
    api_host="localhost",
    api_port=8000,
    auto_start_server=False  # Won't auto-start, fails if no server
)
```

### Easy Client Usage

The easy client syntax also benefits from auto-start:

```python
from gleitzeit.easy import t, w
from gleitzeit.client import GleitzeitClient

# Client will auto-start server if needed
client = GleitzeitClient(base_url="http://localhost:8000")
await client.initialize()

# Now use easy syntax
workflow = w(
    t("task1", "python/inline").with_(code="return 'Hello'")
)

result = await client.submit_workflow(workflow.to_dict())
```

## Configuration Loading

### Project Configuration File

Both auto-start methods (client and CLI) now automatically load configuration from `gleitzeit.yaml` if present in the current directory:

```yaml
# gleitzeit.yaml - Project-specific configuration
max_retries: 5
retry_base_delay: 20
retry_max_delay: 600
worker_batch_size: 10
redis_url: "redis://localhost:6379"
stream_consumer_group: "my-workers"
hostname: "my-host"
```

#### How It Works

1. **Automatic Loading**: When starting the server, both methods check for `gleitzeit.yaml` in the current directory
2. **Environment Variable Conversion**: Each config key is converted to uppercase with `GLEITZEIT_` prefix
   - `max_retries` → `GLEITZEIT_MAX_RETRIES`
   - `redis_url` → `GLEITZEIT_REDIS_URL`
3. **Precedence**: Environment variables take precedence over config file values
4. **Error Handling**: If the file doesn't exist or can't be parsed, the server starts with defaults

#### Example Usage

```python
# With gleitzeit.yaml in current directory
client = GleitzeitClient(api_host="localhost", api_port=8000)
await client.initialize()  # Automatically loads gleitzeit.yaml config
```

```bash
# CLI also loads the config
gleitzeit serve  # Loads gleitzeit.yaml if present
gleitzeit submit workflow.yaml  # Auto-start loads config
```

## Implementation Details

### Server Start Methods

The client tries multiple methods to start the server, in order of preference:

1. **`gleitzeit serve` command** (preferred)
   - Uses the official CLI command
   - Includes `--headless` flag for programmatic use
   - Consistent with manual server starts

2. **Direct uvicorn** (fallback)
   - Uses `python -m uvicorn gleitzeit.api.main:app`
   - For environments where CLI isn't installed
   - Ensures library-only installations work

### Cross-Platform Support

The auto-start feature works on Windows, macOS, and Linux:

#### Windows
- Checks for `gleitzeit.cmd` (pip installation)
- Checks for `gleitzeit.exe` (binary distribution)
- Uses `shell=True` for .cmd files
- Falls back to direct Python module execution

#### macOS/Linux
- Checks for `gleitzeit` command
- Standard subprocess execution
- Falls back to direct Python module execution

### Health Check Process

1. **Initial Check**: Before starting, checks if server is already running at the specified host:port
2. **Start Process**: If not running, starts server using appropriate method
3. **Wait Loop**: Polls health endpoint every second for up to 30 seconds
4. **Success/Failure**: Returns when server is ready or raises error after timeout

### Configuration

#### Configuration Sources (in order of precedence)

1. **Environment Variables** (highest priority)
   - Directly set environment variables always take precedence
   - Example: `GLEITZEIT_REDIS_URL=redis://prod-server:6379`

2. **Project Configuration File** (`gleitzeit.yaml`)
   - Loaded automatically if present in current directory
   - Values are converted to environment variables
   - Only used if environment variable not already set

3. **System Defaults** (lowest priority)
   - Built-in defaults in the code
   - Used when neither env vars nor config file specify a value

#### Environment Variables
- `GLEITZEIT_API_HOST`: Default host if not specified (default: localhost)
- `GLEITZEIT_API_PORT`: Default port if not specified (default: 8080)
- `GLEITZEIT_REDIS_URL`: Redis connection URL (default: redis://localhost:6379)
- `GLEITZEIT_MAX_RETRIES`: Maximum retry attempts (default: 3)
- `GLEITZEIT_RETRY_BASE_DELAY`: Base delay between retries in seconds (default: 10)
- `GLEITZEIT_RETRY_MAX_DELAY`: Maximum delay between retries in seconds (default: 300)
- `GLEITZEIT_WORKER_BATCH_SIZE`: Worker batch size (default: 5)
- `GLEITZEIT_WORKER_IDLE_TIMEOUT`: Worker idle timeout in ms (default: 60000)
- `GLEITZEIT_STREAM_CONSUMER_GROUP`: Redis stream consumer group (default: gleitzeit-workers)

#### Parameters
- `api_host`: Server hostname (default: "localhost")
- `api_port`: Server port (default: 8000)
- `auto_start_server`: Enable/disable auto-start (default: True)

## Error Handling

### Timeout
If the server doesn't start within 30 seconds, a `SystemError` is raised:
```python
SystemError: Failed to start SystemManager server at localhost:8000
```

### Server Already Running
If a server is already running on the specified port, the client connects to it without starting a new instance.

### Permission Errors
On some systems, starting a server might require appropriate permissions. Ensure the user has permission to:
- Execute Python scripts
- Bind to the specified port
- Access required directories

## Best Practices

1. **Use Default Settings**: The default auto-start behavior works well for most use cases

2. **Production Environments**: In production, consider:
   - Running the server as a system service
   - Disabling auto-start (`auto_start_server=False`)
   - Using proper process managers (systemd, supervisor, etc.)

3. **Development**: Auto-start is perfect for development:
   - No need to manually start servers
   - Automatic cleanup on client shutdown
   - Quick iteration and testing

4. **Testing**: For tests, you might want to:
   - Use different ports for parallel tests
   - Explicitly control server lifecycle
   - Consider using `auto_start_server=False` for test isolation

## Comparison with CLI

The CLI has two different behaviors for server management:

### CLI Commands (submit, status, etc.)
These commands automatically ensure server is running:

```bash
# CLI commands automatically ensure server is running
gleitzeit submit workflow.yaml  # Starts server if needed
gleitzeit status workflow-123   # Starts server if needed
```

### The `gleitzeit serve` Command
The `serve` command now includes intelligent instance management:

```bash
# Normal start - detects if already running
gleitzeit serve

# If server is already running, you'll see:
# ✅ SystemManager server already running on 0.0.0.0:8000
#    Use --restart to restart or --force to kill and start fresh

# Graceful restart (SIGTERM)
gleitzeit serve --restart

# Force restart (SIGKILL)
gleitzeit serve --force

# Start without UI
gleitzeit serve --headless

# Custom ports
gleitzeit serve --port 8080 --ui-port 8081
```

#### Restart Options

**`--restart`** (Graceful):
- Sends `SIGTERM` signal to existing processes
- Allows processes to clean up resources
- Waits 2 seconds before starting new server
- Recommended for normal use

**`--force`** (Immediate):
- Sends `SIGKILL` signal to existing processes
- Immediate termination without cleanup
- Use when server is unresponsive
- May leave resources in inconsistent state

Both the client library auto-start and CLI commands use the same underlying mechanism for checking server availability.

## Technical Details

### Code Location
- Client auto-start: `src/gleitzeit/client/client.py:_ensure_system_manager_running()`
- CLI auto-start: `src/gleitzeit/cli/main.py:ensure_server()`
- CLI serve command: `src/gleitzeit/cli/main.py:serve()`

### Dependencies
- `shutil.which()`: For finding executables
- `subprocess.Popen()`: For starting server process
- `aiohttp`/`httpx`: For health checks
- `platform.system()`: For OS detection
- `os.kill()`: For process termination (restart/force)
- `signal`: For SIGTERM/SIGKILL signals
- `lsof`: For finding processes by port (Unix/Mac)

### Process Management
- Server runs as a subprocess
- Output redirected to `DEVNULL` to avoid cluttering console
- Process continues running after client exits (daemon-like)

## Troubleshooting

### Server Won't Start
1. Check if port is already in use: `lsof -i:8000`
2. Verify Python installation: `python --version`
3. Check Gleitzeit installation: `gleitzeit --version`
4. Look for error logs in console output

### Windows Issues
1. Ensure Python is in PATH
2. Check Windows Firewall settings
3. Try running with administrator privileges if needed

### Connection Refused
1. Verify the host and port are correct
2. Check network connectivity
3. Ensure no proxy is interfering
4. Try `localhost` instead of `127.0.0.1`

## Migration Guide

### From Manual Start
Before:
```python
# Terminal 1
$ gleitzeit serve --port 8000

# Terminal 2
client = GleitzeitClient(api_port=8000)
```

After:
```python
# Single terminal - server starts automatically
client = GleitzeitClient(api_port=8000)
await client.initialize()
```

### From Direct uvicorn
Before:
```python
subprocess.Popen(["uvicorn", "gleitzeit.api.main:app"])
client = GleitzeitClient()
```

After:
```python
# Just use the client - it handles server start
client = GleitzeitClient()
await client.initialize()
```

## Future Enhancements

Potential improvements for the auto-start feature:

1. **Process Management**: Better tracking of started processes
2. **Cleanup**: Automatic shutdown of auto-started servers
3. **Multiple Servers**: Support for multiple server instances
4. **Configuration**: More granular control over startup behavior
5. **Logging**: Better visibility into auto-start process
6. **Recovery**: Automatic restart on server crashes