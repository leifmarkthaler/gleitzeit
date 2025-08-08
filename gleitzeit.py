#!/usr/bin/env python3
"""
Gleitzeit Entry Point

Simple entry point for Gleitzeit CLI, similar to how 'jupyter' works.

Usage:
    python gleitzeit.py serve
    python gleitzeit.py serve --port 8080
    python gleitzeit.py version
"""

import sys
from pathlib import Path

# Add the package to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run CLI
from gleitzeit_cluster.cli import main

if __name__ == "__main__":
    main()