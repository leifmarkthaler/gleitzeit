# Gleitzeit Restart Functionality Documentation

## Overview
The `--restart` flag enables Gleitzeit instances to forcefully take over ports from existing processes, ensuring clean service startup even when previous instances have not shut down properly or are running in background loops.

## Usage

```bash
# Start Gleitzeit with restart capability
gleitzeit serve --restart

# With custom instance name
gleitzeit serve --instance-name "my-instance" --restart
```

## How It Works

### 1. Port Lock Management
Gleitzeit uses file-based locks (`fcntl`) combined with Redis-based distributed port allocation to manage port ownership across instances.

### 2. Process Detection
When acquiring a port with `--restart`, the system:
- Checks for existing file locks on the port
- Uses `psutil` to detect processes using the port
- Falls back to `lsof` command if psutil fails to detect the process

### 3. Process Tree Termination
The restart functionality implements comprehensive process killing that handles:
- **Direct processes**: Processes directly listening on the port
- **Parent shell processes**: Detects and kills parent shell processes (bash, sh, zsh, fish)
- **Child processes**: Recursively terminates all child processes
- **Auto-restart loops**: Handles cases where processes are running in shell restart loops

### 4. Retry Logic
After killing processes, the system:
- Attempts to acquire the port lock multiple times
- Cleans up stale lock files between attempts
- Re-checks for processes that may have restarted
- Implements exponential backoff between retries

## Implementation Details

### Key Components

#### `ProcessManager._kill_process_tree()`
Terminates an entire process tree, including:
- Detection of parent shell processes running restart loops
- Recursive termination of all child processes
- Force killing of surviving processes after timeout

#### `ProcessManager._find_process_on_port()`
Multi-method process detection:
1. Uses `psutil.process_iter()` to check process connections
2. Falls back to `lsof -ti :PORT` command for additional coverage
3. Returns the process object for termination

#### Port Lock Acquisition Flow
1. Check if port lock can be acquired
2. If locked by another instance and `kill_existing=True`:
   - Find process on port
   - Kill entire process tree
   - Remove stale lock file
   - Retry lock acquisition (up to 3 attempts)
3. If port in use but no lock owner:
   - Detect external process
   - Kill if `kill_existing=True`
   - Clean up and retry

## Common Scenarios

### Scenario 1: Previous Instance Crash
When a previous Gleitzeit instance crashes without releasing ports:
```bash
gleitzeit serve --restart
# Automatically cleans up stale locks and starts fresh
```

### Scenario 2: Shell Restart Loop
When a UI server is running in a shell restart loop:
```bash
# Background process running:
# while true; do python -m uvicorn app:app --port 8004 --reload; done

gleitzeit serve --restart
# Detects parent shell, kills entire process tree
```

### Scenario 3: Multiple Instances
When multiple instances need to share resources:
```bash
# Instance 1 (running)
gleitzeit serve --instance-name "prod"

# Instance 2 (needs to take over)
gleitzeit serve --instance-name "prod-v2" --restart
# Kills instance 1's processes and takes over ports
```

## Error Handling

### Lock File Corruption
If lock files become corrupted:
- System automatically removes invalid lock files
- Creates fresh locks after cleanup

### Permission Issues
If processes cannot be killed due to permissions:
- Logs warning about failed termination
- Continues with remaining cleanup steps
- May require manual intervention or sudo privileges

### Race Conditions
Multiple instances trying to acquire same port:
- File-based locks provide atomicity
- First instance to acquire lock wins
- Others retry or fail based on configuration

## Configuration

### Environment Variables
- `GLEITZEIT_PORT_LOCK_DIR`: Directory for port lock files (default: `/tmp/gleitzeit/locks`)
- `GLEITZEIT_PORT_RETRY_ATTEMPTS`: Number of retry attempts (default: 3)
- `GLEITZEIT_PORT_RETRY_DELAY`: Delay between retries in seconds (default: 1)

### Port Ranges
Default ports allocated by Gleitzeit:
- API Server: 8000-8003
- UI Server: 8004-8007
- Workers: 8008+

## Troubleshooting

### Port Still In Use After Restart
1. Check for processes with elevated privileges:
   ```bash
   sudo lsof -i :PORT
   ```
2. Manually kill stubborn processes:
   ```bash
   sudo kill -9 $(lsof -ti:PORT)
   ```

### Lock Files Not Cleaned Up
1. Check lock directory:
   ```bash
   ls -la /tmp/gleitzeit/locks/
   ```
2. Remove stale locks manually:
   ```bash
   rm /tmp/gleitzeit/locks/port_*.lock
   ```

### Debugging Restart Issues
Enable debug logging:
```bash
export GLEITZEIT_LOG_LEVEL=DEBUG
gleitzeit serve --restart
```

## Best Practices

1. **Use Named Instances**: Always use `--instance-name` for better tracking
2. **Monitor Logs**: Check logs for restart actions and failures
3. **Graceful Shutdown**: When possible, use graceful shutdown instead of restart
4. **Resource Cleanup**: Periodically clean up `/tmp/gleitzeit/locks/` directory

## Security Considerations

- Port locks are created with user permissions only
- Process termination respects OS permission boundaries
- Lock files should not be shared across security boundaries
- Consider using separate Redis databases for different environments

## Performance Impact

- Process detection: ~100ms overhead
- Process termination: 2-5 seconds depending on process tree size
- Lock acquisition: Minimal overhead (<10ms)
- Retry logic: Adds up to 10 seconds in worst case

## Future Enhancements

- [ ] Configurable retry strategies
- [ ] Port reservation system for planned maintenance
- [ ] Integration with systemd/launchd for process management
- [ ] Distributed lock coordination across machines
- [ ] Health check based restart triggers