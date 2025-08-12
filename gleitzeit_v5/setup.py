#!/usr/bin/env python3
"""
Setup script for Gleitzeit V5 - Modern workflow orchestration
"""

from setuptools import setup, find_packages
import os
from pathlib import Path

# Read README if it exists
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    with open(readme_path) as f:
        long_description = f.read()

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    with open(requirements_path) as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]
else:
    # Default requirements for V5
    requirements = [
        "python-socketio>=5.8.0",
        "aiohttp>=3.8.0",
        "pydantic>=2.0.0",
        "pyyaml>=6.0.0",
        "httpx>=0.24.0",
        "rich>=13.0.0",  # For beautiful CLI output
        "click>=8.0.0",
        "asyncio-mqtt>=0.13.0",
    ]

setup(
    name="gleitzeit-v5",
    version="5.0.0-alpha",
    description="Gleitzeit V5 - Modern workflow orchestration with Socket.IO",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Leif Markthaler",
    author_email="leif.markthaler@gmail.com",
    url="https://github.com/leifmarkthaler/gleitzeit",
    packages=find_packages(include=["gleitzeit_v5*"]),
    include_package_data=True,
    package_data={
        'gleitzeit_v5': [
            'protocols/yaml/*.yaml',
            'providers/yaml/*.yaml',
            'examples/*.yaml',
            'examples/*.json',
        ],
    },
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-asyncio>=0.21.0',
            'black>=23.0.0',
            'mypy>=1.0.0',
            'ruff>=0.1.0',
        ],
        'all': [
            'redis>=4.5.0',  # For advanced clustering
            'pillow>=10.0.0',  # For image processing workflows
        ],
    },
    entry_points={
        'console_scripts': [
            'gleitzeit5=gleitzeit_v5.cli:run',
            'gv5=gleitzeit_v5.cli:run',  # Short alias
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "Topic :: System :: Distributed Computing",
        "Topic :: System :: Systems Administration",
    ],
    keywords=[
        "workflow", 
        "orchestration", 
        "distributed", 
        "socketio", 
        "async", 
        "real-time",
        "components",
        "microservices"
    ],
    project_urls={
        "Homepage": "https://github.com/leifmarkthaler/gleitzeit",
        "Documentation": "https://github.com/leifmarkthaler/gleitzeit#readme",
        "Repository": "https://github.com/leifmarkthaler/gleitzeit",
        "Bug Reports": "https://github.com/leifmarkthaler/gleitzeit/issues",
    },
)