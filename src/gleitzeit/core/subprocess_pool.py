"""
Subprocess pool for efficient Python code execution.

Maintains a pool of warm Python processes to avoid startup overhead.
Each subprocess creation typically takes 50-100ms, which this eliminates.
"""

import asyncio
import json
import sys
import os
import tempfile
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from pathlib import Path
import time
import uuid
from asyncio import Queue
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


@dataclass
class PooledProcess:
    """A pooled Python subprocess"""
    process: asyncio.subprocess.Process
    id: str
    created_at: float
    last_used: float
    use_count: int = 0
    is_busy: bool = False


class PythonSubprocessPool:
    """
    Pool of Python subprocesses for code execution.

    Maintains warm processes that can execute code without startup overhead.
    """

    def __init__(
        self,
        min_size: int = 2,
        max_size: int = 10,
        max_age_seconds: float = 300,  # 5 minutes
        max_uses: int = 100  # Restart process after N uses
    ):
        self.min_size = min_size
        self.max_size = max_size
        self.max_age = max_age_seconds
        self.max_uses = max_uses

        self._pool: List[PooledProcess] = []
        self._available: Queue = Queue()
        self._lock = asyncio.Lock()
        self._initialized = False
        self._shutdown = False

        # Executor script that processes will run
        self._executor_script = self._create_executor_script()

    def _create_executor_script(self) -> str:
        """Create the executor script that runs in each subprocess"""
        script = '''
import json
import sys
import traceback

def execute_code(code_str, inputs_dict):
    """Execute code and return result"""
    import io
    import sys

    # Setup execution environment
    globals_dict = {"__name__": "__main__"}
    locals_dict = {"inputs": inputs_dict}

    try:
        # Capture stdout during code execution to prevent pollution
        old_stdout = sys.stdout
        captured_stdout = io.StringIO()
        sys.stdout = captured_stdout

        # Execute the code
        exec(code_str, globals_dict, locals_dict)

        # Restore stdout
        sys.stdout = old_stdout
        captured_output = captured_stdout.getvalue()

        # Extract result
        if "result" in locals_dict:
            return {
                "success": True,
                "result": locals_dict["result"],
                "stdout": captured_output if captured_output else None
            }
        elif "output" in locals_dict:
            return {
                "success": True,
                "result": locals_dict["output"],
                "stdout": captured_output if captured_output else None
            }
        else:
            return {
                "success": True,
                "result": captured_output if captured_output else None,
                "stdout": captured_output if captured_output else None
            }

    except Exception as e:
        # Restore stdout in case of exception
        sys.stdout = old_stdout
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

# Main loop - process commands
while True:
    try:
        # Read command (ensure we flush and handle buffering)
        sys.stdout.flush()  # Ensure any previous output is flushed
        line = sys.stdin.readline()
        if not line:
            break

        command = json.loads(line)

        if command["type"] == "ping":
            # Health check
            response = {"type": "pong", "id": command.get("id")}

        elif command["type"] == "execute":
            # Execute code
            result = execute_code(
                command["code"],
                command.get("inputs", {})
            )
            response = {
                "type": "result",
                "id": command.get("id"),
                **result
            }

        elif command["type"] == "shutdown":
            # Clean shutdown
            response = {"type": "goodbye", "id": command.get("id")}
            print(json.dumps(response), flush=True)
            break

        else:
            response = {
                "type": "error",
                "id": command.get("id"),
                "error": f"Unknown command type: {command['type']}"
            }

        # Send response
        print(json.dumps(response), flush=True)

    except json.JSONDecodeError as e:
        response = {"type": "error", "error": f"Invalid JSON: {e}"}
        print(json.dumps(response), flush=True)
    except Exception as e:
        response = {"type": "error", "error": str(e)}
        print(json.dumps(response), flush=True)
'''

        # Write to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            return f.name

    async def initialize(self):
        """Initialize the pool with minimum processes"""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info(f"Initializing Python subprocess pool (min={self.min_size}, max={self.max_size})")

            # Start minimum number of processes
            for _ in range(self.min_size):
                process = await self._create_process()
                if process:
                    self._pool.append(process)
                    await self._available.put(process)

            self._initialized = True
            logger.info(f"Subprocess pool initialized with {len(self._pool)} processes")

    async def _create_process(self) -> Optional[PooledProcess]:
        """Create a new pooled process"""
        try:
            # Start subprocess running our executor script
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                self._executor_script,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024*1024  # 1MB buffer
            )

            pooled = PooledProcess(
                process=process,
                id=str(uuid.uuid4())[:8],
                created_at=time.time(),
                last_used=time.time()
            )

            # Test the process with a ping
            await self._send_command(pooled, {"type": "ping"})

            logger.debug(f"Created new subprocess {pooled.id}")
            return pooled

        except Exception as e:
            logger.error(f"Failed to create subprocess: {e}")
            return None

    async def _send_command(self, process: PooledProcess, command: Dict) -> Dict:
        """Send command to process and get response"""
        command_json = json.dumps(command) + '\n'
        process.process.stdin.write(command_json.encode())
        await process.process.stdin.drain()

        # Read response
        response_line = await process.process.stdout.readline()
        response = json.loads(response_line.decode())

        return response

    async def _check_process_health(self, process: PooledProcess) -> bool:
        """Check if process is still healthy"""
        if process.process.returncode is not None:
            return False

        try:
            # Send ping with timeout
            command = {"type": "ping", "id": str(uuid.uuid4())}
            response = await asyncio.wait_for(
                self._send_command(process, command),
                timeout=1.0
            )
            return response.get("type") == "pong"
        except:
            return False

    def _should_retire_process(self, process: PooledProcess) -> bool:
        """Check if process should be retired"""
        now = time.time()

        # Check age
        if now - process.created_at > self.max_age:
            logger.debug(f"Retiring process {process.id} due to age")
            return True

        # Check use count
        if process.use_count >= self.max_uses:
            logger.debug(f"Retiring process {process.id} due to use count")
            return True

        return False

    @asynccontextmanager
    async def acquire(self):
        """Acquire a process from the pool"""
        if not self._initialized:
            await self.initialize()

        process = None
        try:
            # Try to get an available process
            while not self._shutdown:
                try:
                    # Wait with timeout
                    process = await asyncio.wait_for(
                        self._available.get(),
                        timeout=1.0
                    )

                    # Check if process should be retired
                    if self._should_retire_process(process):
                        await self._retire_process(process)
                        process = None
                        continue

                    # Check process health
                    if not await self._check_process_health(process):
                        await self._retire_process(process)
                        process = None
                        continue

                    # Mark as busy and yield
                    process.is_busy = True
                    yield process
                    break

                except asyncio.TimeoutError:
                    # Check if we can create more processes
                    async with self._lock:
                        if len(self._pool) < self.max_size:
                            new_process = await self._create_process()
                            if new_process:
                                self._pool.append(new_process)
                                process = new_process
                                process.is_busy = True
                                yield process
                                break

                    # Otherwise continue waiting
                    continue

        finally:
            if process and not self._shutdown:
                # Update stats
                process.use_count += 1
                process.last_used = time.time()
                process.is_busy = False

                # Return to pool if still healthy
                if await self._check_process_health(process):
                    await self._available.put(process)
                else:
                    await self._retire_process(process)

    async def _retire_process(self, process: PooledProcess):
        """Retire a process from the pool"""
        logger.debug(f"Retiring process {process.id}")

        try:
            # Send shutdown command
            await asyncio.wait_for(
                self._send_command(process, {"type": "shutdown"}),
                timeout=1.0
            )
        except:
            pass

        # Terminate if still running
        if process.process.returncode is None:
            process.process.terminate()
            try:
                await asyncio.wait_for(process.process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.process.kill()
                await process.process.wait()

        # Remove from pool
        async with self._lock:
            if process in self._pool:
                self._pool.remove(process)

            # Ensure minimum pool size
            if len(self._pool) < self.min_size and not self._shutdown:
                new_process = await self._create_process()
                if new_process:
                    self._pool.append(new_process)
                    await self._available.put(new_process)

    async def execute_code(self, code: str, inputs: Dict[str, Any] = None) -> Any:
        """Execute code using a pooled process"""
        async with self.acquire() as process:
            # Send execute command
            command = {
                "type": "execute",
                "id": str(uuid.uuid4()),
                "code": code,
                "inputs": inputs or {}
            }

            # Execute with timeout
            response = await asyncio.wait_for(
                self._send_command(process, command),
                timeout=300.0  # 5 minute timeout
            )

            if response.get("success"):
                # Return both result and stdout for better debugging
                result = response.get("result")
                stdout = response.get("stdout")

                # If there's captured stdout, include it in the response
                if stdout:
                    if isinstance(result, dict):
                        # Add stdout to dict result
                        result["_stdout"] = stdout
                        return result
                    else:
                        # Return object with both result and stdout
                        return {"result": result, "_stdout": stdout}
                else:
                    return result
            else:
                # Return the error response from subprocess
                # The response already has the correct structure:
                # {"success": False, "error": str(e), "traceback": traceback.format_exc()}
                return response

    async def shutdown(self):
        """Shutdown the pool and all processes"""
        self._shutdown = True

        logger.info("Shutting down subprocess pool")

        # Retire all processes
        async with self._lock:
            for process in self._pool:
                await self._retire_process(process)

        # Clean up executor script
        try:
            Path(self._executor_script).unlink()
        except:
            pass

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics"""
        now = time.time()

        busy_count = sum(1 for p in self._pool if p.is_busy)
        available_count = sum(1 for p in self._pool if not p.is_busy)

        avg_age = 0
        avg_uses = 0
        if self._pool:
            avg_age = sum(now - p.created_at for p in self._pool) / len(self._pool)
            avg_uses = sum(p.use_count for p in self._pool) / len(self._pool)

        return {
            "pool_size": len(self._pool),
            "busy": busy_count,
            "available": available_count,
            "average_age_seconds": avg_age,
            "average_uses": avg_uses,
            "min_size": self.min_size,
            "max_size": self.max_size
        }


# Global pool instance
_global_pool: Optional[PythonSubprocessPool] = None


def get_subprocess_pool(
    min_size: int = 2,
    max_size: int = 10
) -> PythonSubprocessPool:
    """Get or create the global subprocess pool"""
    global _global_pool

    if _global_pool is None:
        _global_pool = PythonSubprocessPool(
            min_size=min_size,
            max_size=max_size
        )

    return _global_pool