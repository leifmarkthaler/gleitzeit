"""
File Loader Worker for Gleitzeit 0.0.7

Handles loading files (text, images, documents) and making them available to workflows.
Supports various file types and converts them to appropriate formats for task handlers.
"""

import asyncio
import aiofiles
import base64
import json
import logging
import mimetypes
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import hashlib
import uuid

from .base import BaseWorker, WorkerConfig
from ..core.sharding import default_sharding
from ..core.errors import WorkflowValidationError, ConfigurationError

logger = logging.getLogger(__name__)


class FileLoaderConfig:
    """Configuration for file loader with security limits"""

    # Size limits
    MAX_FILE_SIZE_MB = 50
    MAX_TEXT_FILE_SIZE_MB = 10
    MAX_IMAGE_SIZE_MB = 25

    # Security
    ALLOWED_EXTENSIONS = {
        'text': ['.txt', '.md', '.json', '.yaml', '.yml', '.csv', '.log', '.xml', '.html'],
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'],
        'document': ['.pdf', '.doc', '.docx', '.odt'],
        'code': ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php']
    }

    BLOCKED_EXTENSIONS = ['.exe', '.dll', '.so', '.dylib', '.app', '.deb', '.rpm']

    # Cache settings
    CACHE_TTL_SECONDS = 3600  # 1 hour

    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        import os
        config = cls()

        if max_size := os.getenv('GLEITZEIT_MAX_FILE_SIZE_MB'):
            config.MAX_FILE_SIZE_MB = int(max_size)

        if allowed_exts := os.getenv('GLEITZEIT_ALLOWED_FILE_EXTENSIONS'):
            # Parse comma-separated extensions
            exts = allowed_exts.split(',')
            config.ALLOWED_EXTENSIONS['custom'] = exts

        return config


class FileLoaderWorker(BaseWorker):
    """
    Worker that loads files and makes them available to workflows.

    Features:
    - Load text files as strings
    - Load images as base64 encoded data
    - File caching to avoid repeated reads
    - Security validation (size, type, path)
    - Support for multiple file formats
    """

    def __init__(self, config: WorkerConfig):
        super().__init__(config)
        self.loader_config = FileLoaderConfig.from_env()

        # File cache: file_hash -> (content, loaded_at, metadata)
        self.file_cache = {}

        # Track active file loads to prevent duplicates
        self.loading_files = {}

    async def on_initialize(self):
        """Initialize file loader resources"""
        logger.info(f"FileLoaderWorker initialized with max file size: {self.loader_config.MAX_FILE_SIZE_MB}MB")

        # Log supported file types
        all_extensions = []
        for category, exts in self.loader_config.ALLOWED_EXTENSIONS.items():
            all_extensions.extend(exts)
        logger.info(f"Supported file extensions: {', '.join(sorted(set(all_extensions)))}")

    def get_base_streams(self) -> List[str]:
        """Return streams this worker consumes from"""
        return ["file:load", "file:preload"]

    async def process_message(self, stream: str, message_id: str, data: Dict) -> bool:
        """Process file load request

        Message format:
        {
            "file_path": "/path/to/file.txt",
            "task_id": "task-123",
            "workflow_id": "workflow-abc",
            "encoding": "utf-8",  # Optional, for text files
            "as_base64": false,   # Optional, force base64 encoding
            "cache": true         # Optional, whether to cache the file
        }
        """
        file_path = data.get('file_path')
        task_id = data.get('task_id')
        workflow_id = data.get('workflow_id')

        if not file_path:
            logger.error(f"Missing file_path in message {message_id}")
            return True  # ACK malformed message

        logger.info(f"Loading file {file_path} for task {task_id} in workflow {workflow_id}")

        try:
            # Load and validate file
            file_data = await self.load_file(
                file_path,
                encoding=data.get('encoding', 'utf-8'),
                as_base64=data.get('as_base64', False),
                use_cache=data.get('cache', True)
            )

            # Store file data for task
            if task_id and workflow_id:
                # Store in Redis for task to access
                file_key = default_sharding.get_workflow_key(f"files:{task_id}", workflow_id)
                await self.redis.hset(
                    file_key.encode(),
                    mapping={
                        b"content": file_data['content'].encode() if isinstance(file_data['content'], str) else file_data['content'],
                        b"metadata": json.dumps(file_data['metadata']).encode(),
                        b"loaded_at": datetime.utcnow().isoformat().encode()
                    }
                )

                # Set TTL on file data
                await self.redis.expire(file_key.encode(), self.loader_config.CACHE_TTL_SECONDS)

                # Emit success event
                await self.redis.xadd(
                    default_sharding.get_stream_key("file:loaded", workflow_id).encode(),
                    {
                        b"task_id": task_id.encode(),
                        b"workflow_id": workflow_id.encode(),
                        b"file_path": file_path.encode(),
                        b"file_size": str(file_data['metadata']['size']).encode(),
                        b"file_type": file_data['metadata']['type'].encode(),
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )

                logger.info(f"File {file_path} loaded successfully for task {task_id}")

            return True  # Successfully processed

        except (FileNotFoundError, PermissionError, ValueError) as e:
            # File errors are not retryable
            logger.error(f"File load failed: {e}")

            # Emit failure event
            if workflow_id:
                await self.redis.xadd(
                    default_sharding.get_stream_key("file:load:failed", workflow_id).encode(),
                    {
                        b"task_id": (task_id or "").encode(),
                        b"workflow_id": workflow_id.encode(),
                        b"file_path": file_path.encode(),
                        b"error": str(e).encode(),
                        b"timestamp": datetime.utcnow().isoformat().encode()
                    }
                )

            return True  # Don't retry file errors

        except Exception as e:
            # Other errors might be retryable
            logger.error(f"Unexpected error loading file: {e}", exc_info=True)
            return False  # Retry

    async def load_file(
        self,
        file_path: str,
        encoding: str = 'utf-8',
        as_base64: bool = False,
        use_cache: bool = True
    ) -> Dict[str, Any]:
        """Load a file and return its content with metadata"""

        path = Path(file_path)

        # Validate file path
        self._validate_file_path(path)

        # Check file existence and size
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_size_mb = path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.loader_config.MAX_FILE_SIZE_MB:
            raise ValueError(
                f"File too large: {file_size_mb:.2f}MB "
                f"(max: {self.loader_config.MAX_FILE_SIZE_MB}MB)"
            )

        # Check cache
        file_hash = self._get_file_hash(path)
        if use_cache and file_hash in self.file_cache:
            cached = self.file_cache[file_hash]
            # Check if cache is still valid
            cache_age = (datetime.utcnow() - cached['loaded_at']).total_seconds()
            if cache_age < self.loader_config.CACHE_TTL_SECONDS:
                logger.debug(f"Using cached file: {file_path}")
                return cached

        # Detect file type
        mime_type, _ = mimetypes.guess_type(str(path))
        file_ext = path.suffix.lower()
        file_category = self._get_file_category(file_ext)

        # Load file based on type
        if file_category == 'image' or as_base64:
            content = await self._load_binary_file(path, as_base64=True)
        elif file_category in ['text', 'code', 'document']:
            if file_ext in ['.pdf', '.doc', '.docx']:
                # Binary documents need special handling or base64
                content = await self._load_binary_file(path, as_base64=True)
            else:
                content = await self._load_text_file(path, encoding)
        else:
            # Default to text for unknown types
            try:
                content = await self._load_text_file(path, encoding)
            except UnicodeDecodeError:
                # Fall back to base64 for binary files
                content = await self._load_binary_file(path, as_base64=True)

        # Create file data
        file_data = {
            'content': content,
            'metadata': {
                'path': str(path),
                'name': path.name,
                'extension': file_ext,
                'size': path.stat().st_size,
                'type': mime_type or 'application/octet-stream',
                'category': file_category,
                'encoding': encoding if isinstance(content, str) else 'base64',
                'hash': file_hash
            },
            'loaded_at': datetime.utcnow()
        }

        # Cache the file
        if use_cache:
            self.file_cache[file_hash] = file_data
            # Clean old cache entries
            self._clean_cache()

        return file_data

    async def _load_text_file(self, path: Path, encoding: str) -> str:
        """Load a text file"""
        async with aiofiles.open(path, 'r', encoding=encoding) as f:
            return await f.read()

    async def _load_binary_file(self, path: Path, as_base64: bool = False) -> bytes:
        """Load a binary file, optionally as base64"""
        async with aiofiles.open(path, 'rb') as f:
            content = await f.read()

        if as_base64:
            return base64.b64encode(content).decode('utf-8')
        return content

    def _validate_file_path(self, path: Path):
        """Validate file path for security"""
        # Resolve to absolute path
        abs_path = path.resolve()

        # Check for path traversal attempts
        if ".." in str(path):
            raise ValueError(f"Path traversal detected: {path}")

        # Check extension
        ext = path.suffix.lower()
        if ext in self.loader_config.BLOCKED_EXTENSIONS:
            raise ValueError(f"Blocked file type: {ext}")

        # Check if extension is allowed (if restrictions are set)
        all_allowed = []
        for exts in self.loader_config.ALLOWED_EXTENSIONS.values():
            all_allowed.extend(exts)

        if all_allowed and ext not in all_allowed:
            logger.warning(f"File extension {ext} not in allowed list, proceeding with caution")

    def _get_file_category(self, extension: str) -> str:
        """Determine file category from extension"""
        for category, extensions in self.loader_config.ALLOWED_EXTENSIONS.items():
            if extension in extensions:
                return category
        return 'unknown'

    def _get_file_hash(self, path: Path) -> str:
        """Get hash of file for caching"""
        # Use file path and modification time for quick hash
        stat = path.stat()
        hash_input = f"{path}:{stat.st_mtime}:{stat.st_size}"
        return hashlib.md5(hash_input.encode()).hexdigest()

    def _clean_cache(self):
        """Remove old entries from cache"""
        now = datetime.utcnow()
        expired = []

        for file_hash, data in self.file_cache.items():
            age = (now - data['loaded_at']).total_seconds()
            if age > self.loader_config.CACHE_TTL_SECONDS:
                expired.append(file_hash)

        for file_hash in expired:
            del self.file_cache[file_hash]

        if expired:
            logger.debug(f"Cleaned {len(expired)} expired cache entries")

    async def preload_files(self, file_paths: List[str], workflow_id: str):
        """Preload multiple files for a workflow"""
        logger.info(f"Preloading {len(file_paths)} files for workflow {workflow_id}")

        results = []
        for file_path in file_paths:
            try:
                file_data = await self.load_file(file_path, use_cache=True)

                # Store in Redis
                file_key = default_sharding.get_workflow_key(f"preloaded:{Path(file_path).name}", workflow_id)
                await self.redis.hset(
                    file_key.encode(),
                    mapping={
                        b"content": file_data['content'].encode() if isinstance(file_data['content'], str) else file_data['content'],
                        b"metadata": json.dumps(file_data['metadata']).encode()
                    }
                )
                await self.redis.expire(file_key.encode(), self.loader_config.CACHE_TTL_SECONDS)

                results.append({
                    'path': file_path,
                    'status': 'loaded',
                    'size': file_data['metadata']['size']
                })

            except Exception as e:
                logger.error(f"Failed to preload {file_path}: {e}")
                results.append({
                    'path': file_path,
                    'status': 'failed',
                    'error': str(e)
                })

        return results