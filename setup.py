#!/usr/bin/env python3
"""
Setup script for Gleitzeit - Protocol-based workflow orchestration
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    with open(readme_path, encoding="utf-8") as f:
        long_description = f.read()

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    with open(requirements_path, encoding="utf-8") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="gleitzeit",
    version="0.0.5",
    description="Protocol-based workflow orchestration system with LLM and MCP support",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Leif Markthaler",
    author_email="leif.markthaler@gmail.com",
    url="https://github.com/leifmarkthaler/gleitzeit",
    license="MIT",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    package_data={
        'gleitzeit': [
            'protocols/*.yaml',
            'examples/*.yaml',
            'examples/*.py',
            'examples/*.txt',
            'examples/*.png',
            'examples/*.md',
        ],
    },
    python_requires=">=3.8",
    install_requires=requirements if requirements else [
        "click>=8.0.0",
        "pydantic>=2.0.0",
        "pyyaml>=6.0.0",
        "aiohttp>=3.8.0",
        "jsonschema>=4.0.0",
        "aiosqlite>=0.19.0",
        "redis>=4.5.0",
        "aiofiles>=23.0.0",
        "httpx>=0.24.0",
    ],
    extras_require={
        'dev': [
            'pytest>=7.0.0',
            'pytest-asyncio>=0.21.0',
            'black>=23.0.0',
            'mypy>=1.0.0',
            'ruff>=0.1.0',
        ],
        'llm': [
            'ollama>=0.1.0',
            'openai>=1.0.0',
            'anthropic>=0.7.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'gleitzeit=gleitzeit.cli.gleitzeit_cli:main',
            'gz=gleitzeit.cli.gleitzeit_cli:main',
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
        "Topic :: Software Development :: Libraries :: Application Frameworks",
    ],
    keywords=[
        "workflow", 
        "orchestration", 
        "automation",
        "distributed", 
        "async", 
        "llm",
        "mcp",
        "model-context-protocol",
        "task-automation"
    ],
    project_urls={
        "Homepage": "https://github.com/leifmarkthaler/gleitzeit",
        "Documentation": "https://github.com/leifmarkthaler/gleitzeit#readme",
        "Repository": "https://github.com/leifmarkthaler/gleitzeit",
        "Bug Reports": "https://github.com/leifmarkthaler/gleitzeit/issues",
    },
)