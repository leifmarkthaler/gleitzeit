#!/usr/bin/env python3
"""Debug server startup script"""

import sys
import os
sys.path.insert(0, 'src')

print(f"Initial os: {os}")

try:
    import asyncio
    print("asyncio imported")
    
    import logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    print("logging configured")
    
    # Try importing FastAPI 
    from fastapi import FastAPI
    print("FastAPI imported")
    
    # Try importing gleitzeit modules one by one
    from gleitzeit.core import Task, Workflow, Priority
    print("gleitzeit.core imported")
    
    print(f"os after gleitzeit.core: {os}")
    
    from gleitzeit.core.models import RetryConfig
    print("RetryConfig imported")
    
    print(f"os after RetryConfig: {os}")
    
    from gleitzeit.core.retry_manager import BackoffStrategy
    print("BackoffStrategy imported")
    
    print(f"os after BackoffStrategy: {os}")
    
    from gleitzeit.core.workflow_loader import load_workflow_from_file, validate_workflow
    print("workflow_loader imported")
    
    print(f"os after workflow_loader: {os}")
    
    from gleitzeit.core.log_collector import LogCollector, set_log_collector, get_log_collector
    print("log_collector imported")
    
    print(f"os after log_collector: {os}")
    
    from gleitzeit.core.log_stream import LogStreamManager, set_log_stream_manager, get_log_stream_manager
    print("log_stream imported")
    
    print(f"os after log_stream: {os}")
    
    from gleitzeit.core.logs import LogLevel, LogSource
    print("logs imported")
    
    print(f"os after logs: {os}")
    
    from gleitzeit.common.shutdown import unified_shutdown
    print("shutdown imported")
    
    print(f"os after shutdown: {os}")
    
except Exception as e:
    print(f"Error during imports: {e}")
    import traceback
    traceback.print_exc()