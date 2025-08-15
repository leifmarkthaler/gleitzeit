#!/usr/bin/env python3
"""
Gleitzeit V4 Setup Script
Install the Gleitzeit workflow orchestration system and CLI.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text() if readme_file.exists() else ""

setup(
    name="gleitzeit",
    version="0.0.4",
    description="Protocol-based workflow orchestration system for LLM and task automation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Leif Markthaler",
    author_email="",
    url="https://github.com/leifmarkthaler/gleitzeit",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        # Core dependencies
        "click>=8.0.0",
        "pydantic>=2.0.0",
        "pyyaml>=6.0.0",
        "aiohttp>=3.8.0",
        
        # Persistence backends
        "aiosqlite>=0.19.0",
        "redis>=4.5.0",
        
        # Optional dependencies for providers
        "aiofiles>=23.0.0",
        "httpx>=0.24.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "mypy>=1.0.0",
            "ruff>=0.1.0",
        ],
        "all": [
            "ollama>=0.1.0",
            "openai>=1.0.0",
            "anthropic>=0.7.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "gleitzeit=cli.gleitzeit_cli:main",
            "gz=cli.gleitzeit_cli:main",  # Short alias
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Distributed Computing",
        "Topic :: System :: Systems Administration",
    ],
    keywords="workflow orchestration automation distributed events async",
    project_urls={
        "Bug Reports": "https://github.com/leifmarkthaler/gleitzeit/issues",
        "Source": "https://github.com/leifmarkthaler/gleitzeit",
    },
)