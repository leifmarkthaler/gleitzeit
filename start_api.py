#!/usr/bin/env python3
"""Direct API starter script to bypass CLI issues"""
import sys
import os
sys.path.insert(0, 'src')

# Set environment variables
os.environ['GLEITZEIT_PERSISTENCE_TYPE'] = 'sql'

# Now import and run
import uvicorn
uvicorn.run("gleitzeit.api.main:app", host="127.0.0.1", port=8000)