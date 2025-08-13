#!/usr/bin/env python3

"""
Python Provider V5 for Gleitzeit

A working Python provider that can execute python/execute tasks.
Imported from previous version test files.
"""

import asyncio
import logging
import socketio
import json
import sys
import os
from datetime import datetime
from typing import Dict, Any
import uuid
import subprocess
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PythonProviderV5:
    """Python provider adapted for Socket.IO architecture"""
    
    def __init__(self, provider_id: str = "python-v5"):
        self.provider_id = provider_id
        self.sio = socketio.AsyncClient()
        self.connected = False
        self.tasks_executed = 0
        
        self._setup_events()
    
    def _setup_events(self):
        """Setup event handlers"""
        
        @self.sio.event
        async def connect():
            self.connected = True
            logger.info(f"[{self.provider_id}] Connected to hub")
        
        @self.sio.event
        async def disconnect():
            self.connected = False
            logger.info(f"[{self.provider_id}] Disconnected from hub")
        
        @self.sio.on('connected')
        async def handle_connected(data):
            logger.info(f"[{self.provider_id}] Received welcome from hub")
            
            await asyncio.sleep(0.1)
            
            # Register as provider
            await self.sio.emit('register_component', {
                'component_type': 'provider',
                'component_id': self.provider_id,
                'capabilities': ['python_execution', 'code_execution'],
                'protocol': 'python',
                'version': '0.0.1'
            })
        
        @self.sio.on('component_registered')
        async def handle_registration(data):
            if data.get('component_id') == self.provider_id:
                logger.info(f"[{self.provider_id}] Registered as Python provider")
                
                # Route provider registration to execution engine
                await self.sio.emit('route_event', {
                    'target_component_type': 'execution_engine',
                    'event_name': 'provider_registered',
                    'event_data': {
                        'component_id': self.provider_id,
                        'protocol': 'python',
                        'capabilities': ['python_execution', 'code_execution']
                    }
                })
        
        @self.sio.on('execute_task')
        async def handle_execute_task(data):
            """Execute a Python task"""
            task_id = data['task_id']
            method = data['method']
            parameters = data.get('parameters', {})
            
            logger.info(f"[{self.provider_id}] Executing task {task_id}: {method}")
            
            try:
                if method == "python/execute":
                    result = await self._execute_python(parameters)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                self.tasks_executed += 1
                
                # Route result back to execution engine
                await self.sio.emit('route_event', {
                    'target_component_type': 'execution_engine',
                    'event_name': 'task_execution_result',
                    'event_data': {
                        'task_id': task_id,
                        'result': result,
                        'execution_time_ms': result.get('execution_time', 0) * 1000
                    }
                })
                
                logger.info(f"[{self.provider_id}] Task {task_id} completed successfully")
                
            except Exception as e:
                logger.error(f"[{self.provider_id}] Task {task_id} failed: {e}")
                await self.sio.emit('route_event', {
                    'target_component_type': 'execution_engine',
                    'event_name': 'task_execution_error',
                    'event_data': {
                        'task_id': task_id,
                        'error': str(e),
                        'retryable': False
                    }
                })
    
    async def _execute_python(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Python code safely"""
        code = parameters.get('code', '')
        context = parameters.get('context', {})
        timeout = parameters.get('timeout', 30)
        
        logger.info(f"[{self.provider_id}] Executing Python code: {code[:100]}...")
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Create a temporary file for the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                # Add context variables to the code
                context_code = ""
                for key, value in context.items():
                    if isinstance(value, str):
                        context_code += f"{key} = '{value}'\n"
                    else:
                        context_code += f"{key} = {value}\n"
                
                # Write the full code with result extraction
                full_code = context_code + "\n" + code + "\n"
                
                # Add code to print the result variable at the end for extraction
                full_code += "\n# Extract result for API\n"
                full_code += "if 'result' in locals():\n"
                full_code += "    print('__RESULT__:', result)\n"
                full_code += "else:\n"
                full_code += "    print('__RESULT__: None')\n"
                
                f.write(full_code)
                temp_file = f.name
            
            # Execute the Python code
            try:
                result = subprocess.run(
                    [sys.executable, temp_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                execution_time = asyncio.get_event_loop().time() - start_time
                
                if result.returncode == 0:
                    # Extract the result from the __RESULT__: line in stdout
                    output_lines = result.stdout.strip().split('\n') if result.stdout.strip() else []
                    final_result = "None"
                    
                    # Look for the __RESULT__: line
                    for line in output_lines:
                        if line.startswith('__RESULT__:'):
                            # Extract the value after __RESULT__:
                            result_value = line.split('__RESULT__:', 1)[1].strip()
                            final_result = result_value
                            break
                    
                    # If no __RESULT__ line found, fall back to the last output line
                    if final_result == "None" and output_lines:
                        final_result = output_lines[-1]
                    
                    return {
                        'result': final_result,
                        'output': result.stdout,
                        'success': True,
                        'execution_time': execution_time
                    }
                else:
                    return {
                        'result': "None",
                        'output': result.stdout,
                        'error': result.stderr,
                        'success': False,
                        'execution_time': execution_time
                    }
                    
            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file)
                except:
                    pass
                    
        except subprocess.TimeoutExpired:
            return {
                'result': "None",
                'error': f"Execution timeout after {timeout} seconds",
                'success': False,
                'execution_time': timeout
            }
        except Exception as e:
            execution_time = asyncio.get_event_loop().time() - start_time
            return {
                'result': "None",
                'error': str(e),
                'success': False,
                'execution_time': execution_time
            }
    
    async def connect_to_hub(self, hub_url: str = "http://localhost:8001"):
        """Connect to the hub"""
        await self.sio.connect(hub_url)
        
        # Wait for registration
        for _ in range(50):
            if self.connected:
                await asyncio.sleep(0.1)
                break
            await asyncio.sleep(0.1)
        
        return self.connected
    
    async def disconnect(self):
        """Disconnect from hub"""
        await self.sio.disconnect()

