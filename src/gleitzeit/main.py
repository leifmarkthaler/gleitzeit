#!/usr/bin/env python3
"""
Main entry point for Gleitzeit V4

This script provides the main command-line interface and can also be used
to start Gleitzeit V4 as a service.
"""

import sys
import os
from pathlib import Path

# Add the parent directory to the Python path so we can import gleitzeit_v4
sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_v4.cli import cli

if __name__ == '__main__':
    cli()