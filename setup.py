"""
Setup configuration for Gleitzeit 0.0.7
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="gleitzeit",
    version="0.0.7",
    author="Gleitzeit Team",
    description="Distributed workflow orchestration with worker-based architecture",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourorg/gleitzeit",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Application Frameworks",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "redis>=4.5.0",
        "click>=8.0.0",
        "pyyaml>=6.0",
        "aiohttp>=3.8.0",
        "aiofiles>=23.0.0",
        "psutil>=5.9.0",
        "fastapi>=0.100.0",
        "uvicorn[standard]>=0.23.0",
        "python-multipart>=0.0.6",
        "pydantic>=2.0.0",
        "websockets>=11.0",
        "pyjwt>=2.8.0",
        "httpx>=0.24.0",
        "jinja2>=3.1.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-asyncio>=0.21",
            "black>=22.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "gleitzeit=gleitzeit.cli.main:main",
            "gleitzeit-api=gleitzeit.api.run_server:main",
        ],
    },
)