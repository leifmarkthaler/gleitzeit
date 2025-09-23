"""
Unified File Operations Core for Gleitzeit

Provides consistent file handling across File Handler and Workflow Loader.
Eliminates code duplication and ensures uniform error handling and security validation.
"""

import asyncio
import base64
import logging
import mimetypes
import os
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pathlib import Path
import hashlib

from .errors import GleitzeitError, ErrorCode

logger = logging.getLogger(__name__)


class FileOperationConfig:
    """Unified configuration for all file operations"""

    # Size limits
    MAX_FILE_SIZE_MB = 50        # General files (File Handler)
    MAX_WORKFLOW_SIZE_MB = 100   # Workflow files (Workflow Loader)
    MAX_TEXT_FILE_SIZE_MB = 10   # Text files
    MAX_IMAGE_SIZE_MB = 25       # Image files

    # Security
    ALLOWED_PATH_PREFIXES: List[str] = []  # If set, restrict to these paths
    BLOCKED_EXTENSIONS = ['.exe', '.dll', '.so', '.dylib', '.app', '.deb', '.rpm']

    # File type mappings
    ALLOWED_EXTENSIONS = {
        'text': ['.txt', '.md', '.csv', '.log', '.xml', '.html'],
        'image': ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg'],
        'document': ['.pdf', '.doc', '.docx', '.odt'],
        'code': ['.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php'],
        'yaml': ['.yaml', '.yml'],
        'json': ['.json']
    }

    # Context-specific configurations
    CONTEXT_CONFIGS = {
        'handler': {
            'max_size_mb': 50,
            'allowed_types': ['text', 'image', 'document', 'code'],
            'security_strict': True
        },
        'workflow': {
            'max_size_mb': 100,
            'allowed_types': ['yaml', 'json'],  # Only YAML and JSON for workflows
            'security_strict': True
        },
        'general': {
            'max_size_mb': 50,
            'allowed_types': ['text', 'image', 'document', 'code'],
            'security_strict': False
        }
    }

    @classmethod
    def from_env(cls):
        """Load configuration from environment variables"""
        config = cls()

        if max_file := os.getenv('GLEITZEIT_MAX_FILE_SIZE_MB'):
            config.MAX_FILE_SIZE_MB = int(max_file)

        if max_workflow := os.getenv('GLEITZEIT_MAX_WORKFLOW_SIZE_MB'):
            config.MAX_WORKFLOW_SIZE_MB = int(max_workflow)

        if allowed_paths := os.getenv('GLEITZEIT_ALLOWED_PATHS'):
            config.ALLOWED_PATH_PREFIXES = allowed_paths.split(',')

        if blocked_exts := os.getenv('GLEITZEIT_BLOCKED_EXTENSIONS'):
            config.BLOCKED_EXTENSIONS.extend(blocked_exts.split(','))

        return config


class FileValidator:
    """Unified file validation with context awareness"""

    def __init__(self, config: FileOperationConfig):
        self.config = config

    def validate_path_security(self, path: Path, context: str = "general") -> None:
        """Validate file path for security violations"""

        # Check for path traversal attempts
        if ".." in str(path):
            raise GleitzeitError(
                f"Path traversal detected: {path}",
                code=ErrorCode.FILE_SECURITY_VIOLATION,
                data={
                    'path': str(path),
                    'context': context,
                    'violation': 'path_traversal'
                }
            )

        # Check allowed path prefixes
        if self.config.ALLOWED_PATH_PREFIXES:
            abs_path = path.resolve()
            allowed = any(
                str(abs_path).startswith(prefix)
                for prefix in self.config.ALLOWED_PATH_PREFIXES
            )
            if not allowed:
                raise GleitzeitError(
                    f"File path not in allowed directories: {abs_path}",
                    code=ErrorCode.FILE_SECURITY_VIOLATION,
                    data={
                        'path': str(abs_path),
                        'context': context,
                        'violation': 'path_not_allowed',
                        'allowed_prefixes': self.config.ALLOWED_PATH_PREFIXES
                    }
                )

        # Check blocked extensions
        ext = path.suffix.lower()
        if ext in self.config.BLOCKED_EXTENSIONS:
            raise GleitzeitError(
                f"Blocked file type: {ext}",
                code=ErrorCode.FILE_SECURITY_VIOLATION,
                data={
                    'path': str(path),
                    'extension': ext,
                    'context': context,
                    'violation': 'blocked_extension'
                }
            )

    def validate_file_access(self, path: Path, context: str = "general") -> None:
        """Validate file exists and is accessible"""

        if not path.exists():
            raise GleitzeitError(
                f"File not found: {path}",
                code=ErrorCode.FILE_NOT_FOUND,
                data={'path': str(path), 'context': context}
            )

        if not path.is_file():
            raise GleitzeitError(
                f"Path is not a file: {path}",
                code=ErrorCode.FILE_SYSTEM_ERROR,
                data={'path': str(path), 'context': context}
            )

    def validate_file_size(self, path: Path, context: str = "general") -> float:
        """Validate file size and return size in MB"""

        try:
            file_size_bytes = path.stat().st_size
            file_size_mb = file_size_bytes / (1024 * 1024)
        except PermissionError:
            raise GleitzeitError(
                f"Permission denied accessing file: {path}",
                code=ErrorCode.FILE_PERMISSION_DENIED,
                data={'path': str(path), 'context': context}
            )
        except OSError as e:
            raise GleitzeitError(
                f"I/O error accessing file: {path}",
                code=ErrorCode.FILE_IO_ERROR,
                data={
                    'path': str(path),
                    'context': context,
                    'os_error': str(e),
                    'os_errno': getattr(e, 'errno', None)
                }
            )

        # Get size limit based on context
        context_config = self.config.CONTEXT_CONFIGS.get(context, self.config.CONTEXT_CONFIGS['general'])
        max_size_mb = context_config['max_size_mb']

        if file_size_mb > max_size_mb:
            raise GleitzeitError(
                f"File too large: {path} ({file_size_mb:.2f}MB > {max_size_mb}MB)",
                code=ErrorCode.FILE_TOO_LARGE,
                data={
                    'path': str(path),
                    'size_mb': file_size_mb,
                    'max_mb': max_size_mb,
                    'context': context
                }
            )

        return file_size_mb

    def validate_file_type(self, path: Path, context: str = "general") -> str:
        """Validate and return file category"""

        ext = path.suffix.lower()
        context_config = self.config.CONTEXT_CONFIGS.get(context, self.config.CONTEXT_CONFIGS['general'])
        allowed_types = context_config['allowed_types']

        # Find file category
        file_category = 'unknown'
        for category, extensions in self.config.ALLOWED_EXTENSIONS.items():
            if ext in extensions:
                file_category = category
                break

        # Check if category is allowed for this context
        if context_config['security_strict'] and file_category not in allowed_types:
            raise GleitzeitError(
                f"File type '{file_category}' not allowed in context '{context}': {path}",
                code=ErrorCode.FILE_SECURITY_VIOLATION,
                data={
                    'path': str(path),
                    'extension': ext,
                    'category': file_category,
                    'context': context,
                    'allowed_types': allowed_types,
                    'violation': 'file_type_not_allowed'
                }
            )

        return file_category

    def validate_all(self, path: Path, context: str = "general") -> Dict[str, Any]:
        """Perform all validations and return file info"""

        # Security validation
        self.validate_path_security(path, context)

        # Access validation
        self.validate_file_access(path, context)

        # Size validation
        file_size_mb = self.validate_file_size(path, context)

        # Type validation
        file_category = self.validate_file_type(path, context)

        # Get additional file info
        mime_type, _ = mimetypes.guess_type(str(path))
        stat = path.stat()

        return {
            'path': str(path),
            'name': path.name,
            'extension': path.suffix.lower(),
            'size_bytes': stat.st_size,
            'size_mb': file_size_mb,
            'category': file_category,
            'mime_type': mime_type or 'application/octet-stream',
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'context': context
        }


class FileLoader:
    """Unified file loading with format detection"""

    def __init__(self, config: FileOperationConfig):
        self.config = config

    async def load_text_file(self, path: Path, encoding: str = 'utf-8') -> str:
        """Load a text file with encoding handling"""
        try:
            # Use async file operations for better performance
            with open(path, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError as e:
            raise GleitzeitError(
                f"Encoding error reading file: {path} with encoding {encoding}",
                code=ErrorCode.FILE_ENCODING_ERROR,
                data={
                    'path': str(path),
                    'encoding': encoding,
                    'error_detail': str(e)
                }
            )
        except PermissionError:
            raise GleitzeitError(
                f"Permission denied reading file: {path}",
                code=ErrorCode.FILE_PERMISSION_DENIED,
                data={'path': str(path)}
            )
        except OSError as e:
            if e.errno == 16:  # Device busy / file locked
                raise GleitzeitError(
                    f"File is locked: {path}",
                    code=ErrorCode.FILE_LOCKED,
                    data={'path': str(path)}
                )
            else:
                raise GleitzeitError(
                    f"I/O error reading file: {path}",
                    code=ErrorCode.FILE_IO_ERROR,
                    data={
                        'path': str(path),
                        'os_error': str(e),
                        'os_errno': getattr(e, 'errno', None)
                    }
                )

    async def load_binary_file(self, path: Path, as_base64: bool = False) -> Union[str, bytes]:
        """Load a binary file, optionally as base64"""
        try:
            with open(path, 'rb') as f:
                content = f.read()

            if as_base64:
                return base64.b64encode(content).decode('utf-8')
            return content

        except PermissionError:
            raise GleitzeitError(
                f"Permission denied reading file: {path}",
                code=ErrorCode.FILE_PERMISSION_DENIED,
                data={'path': str(path)}
            )
        except OSError as e:
            if e.errno == 16:  # Device busy / file locked
                raise GleitzeitError(
                    f"File is locked: {path}",
                    code=ErrorCode.FILE_LOCKED,
                    data={'path': str(path)}
                )
            else:
                raise GleitzeitError(
                    f"I/O error reading file: {path}",
                    code=ErrorCode.FILE_IO_ERROR,
                    data={
                        'path': str(path),
                        'os_error': str(e),
                        'os_errno': getattr(e, 'errno', None)
                    }
                )

    async def load_file_auto(
        self,
        path: Path,
        file_category: str,
        encoding: str = 'utf-8',
        as_base64: bool = False
    ) -> Dict[str, Any]:
        """Load file with automatic format detection"""

        if file_category == 'image' or as_base64:
            content = await self.load_binary_file(path, as_base64=True)
            encoding_used = 'base64'
        elif file_category in ['text', 'code', 'workflow']:
            content = await self.load_text_file(path, encoding)
            encoding_used = encoding
        else:
            # Try text first, fall back to base64
            try:
                content = await self.load_text_file(path, encoding)
                encoding_used = encoding
            except GleitzeitError as e:
                if e.code == ErrorCode.FILE_ENCODING_ERROR:
                    content = await self.load_binary_file(path, as_base64=True)
                    encoding_used = 'base64'
                else:
                    raise

        return {
            'content': content,
            'encoding': encoding_used,
            'size': len(content) if isinstance(content, str) else len(content)
        }


class FileOperations:
    """Main file operations interface combining validation and loading"""

    def __init__(self, context: str = "general", config: Optional[FileOperationConfig] = None):
        self.context = context
        self.config = config or FileOperationConfig.from_env()
        self.validator = FileValidator(self.config)
        self.loader = FileLoader(self.config)

    async def load_file(
        self,
        path: Union[str, Path],
        encoding: str = 'utf-8',
        as_base64: bool = False,
        validate: bool = True
    ) -> Dict[str, Any]:
        """Load a file with full validation and metadata"""

        file_path = Path(path) if isinstance(path, str) else path

        # Validation
        if validate:
            file_info = self.validator.validate_all(file_path, self.context)
        else:
            # Minimal info without full validation
            file_info = {
                'path': str(file_path),
                'name': file_path.name,
                'extension': file_path.suffix.lower(),
                'context': self.context
            }

        # Loading
        if validate:
            load_result = await self.loader.load_file_auto(
                file_path,
                file_info['category'],
                encoding,
                as_base64
            )
        else:
            # Simple loading without category detection
            if as_base64 or file_path.suffix.lower() in self.config.ALLOWED_EXTENSIONS.get('image', []):
                load_result = {
                    'content': await self.loader.load_binary_file(file_path, as_base64=True),
                    'encoding': 'base64'
                }
            else:
                load_result = {
                    'content': await self.loader.load_text_file(file_path, encoding),
                    'encoding': encoding
                }

        # Generate file hash for caching
        if validate and 'size_bytes' in file_info:
            hash_input = f"{file_path}:{file_info.get('modified', '')}:{file_info['size_bytes']}"
            file_hash = hashlib.md5(hash_input.encode()).hexdigest()
        else:
            file_hash = None

        return {
            'path': str(file_path),
            'content': load_result['content'],
            'metadata': {
                **file_info,
                'encoding': load_result['encoding'],
                'content_size': load_result.get('size', len(load_result['content'])),
                'hash': file_hash
            }
        }

    async def load_multiple_files(
        self,
        paths: List[Union[str, Path]],
        encoding: str = 'utf-8',
        as_base64: bool = False,
        continue_on_error: bool = True
    ) -> Dict[str, Any]:
        """Load multiple files with error handling"""

        results = []
        for path in paths:
            try:
                file_result = await self.load_file(path, encoding, as_base64)
                results.append({
                    'path': str(path),
                    'status': 'loaded',
                    'content': file_result['content'],
                    'metadata': file_result['metadata']
                })
            except Exception as e:
                if continue_on_error:
                    results.append({
                        'path': str(path),
                        'status': 'failed',
                        'error': str(e),
                        'error_type': type(e).__name__
                    })
                else:
                    raise

        return {
            'files': results,
            'total': len(paths),
            'loaded': len([r for r in results if r['status'] == 'loaded']),
            'failed': len([r for r in results if r['status'] == 'failed'])
        }

    def list_directory(
        self,
        directory: Union[str, Path],
        pattern: str = '*',
        recursive: bool = False,
        include_hidden: bool = False
    ) -> Dict[str, Any]:
        """List files in directory with optional filtering"""

        dir_path = Path(directory) if isinstance(directory, str) else directory

        # Validate directory
        self.validator.validate_path_security(dir_path, self.context)

        if not dir_path.exists():
            raise GleitzeitError(
                f"Directory not found: {directory}",
                code=ErrorCode.FILE_NOT_FOUND,
                data={'path': str(dir_path), 'context': self.context}
            )

        if not dir_path.is_dir():
            raise GleitzeitError(
                f"Path is not a directory: {directory}",
                code=ErrorCode.FILE_SYSTEM_ERROR,
                data={'path': str(dir_path), 'context': self.context}
            )

        files = []
        try:
            if recursive:
                paths = dir_path.rglob(pattern)
            else:
                paths = dir_path.glob(pattern)

            for path in paths:
                if not include_hidden and path.name.startswith('.'):
                    continue

                try:
                    stat = path.stat()
                    files.append({
                        'path': str(path),
                        'name': path.name,
                        'size': stat.st_size,
                        'is_file': path.is_file(),
                        'is_dir': path.is_dir(),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        'extension': path.suffix.lower() if path.is_file() else None
                    })
                except (OSError, PermissionError) as e:
                    logger.warning(f"Cannot access {path}: {e}")

        except PermissionError:
            raise GleitzeitError(
                f"Permission denied listing directory: {directory}",
                code=ErrorCode.FILE_PERMISSION_DENIED,
                data={'path': str(dir_path), 'context': self.context}
            )

        return {
            'directory': str(dir_path),
            'pattern': pattern,
            'files': sorted(files, key=lambda f: f['name']),
            'count': len(files),
            'context': self.context
        }

    def file_exists(self, path: Union[str, Path]) -> Dict[str, Any]:
        """Check if file exists with metadata"""

        file_path = Path(path) if isinstance(path, str) else path
        exists = file_path.exists()

        result = {
            'path': str(file_path),
            'exists': exists,
            'context': self.context
        }

        if exists:
            try:
                result.update({
                    'is_file': file_path.is_file(),
                    'is_dir': file_path.is_dir(),
                    'size': file_path.stat().st_size if file_path.is_file() else None
                })
            except (OSError, PermissionError):
                result.update({
                    'is_file': None,
                    'is_dir': None,
                    'size': None,
                    'access_denied': True
                })

        return result


# Global instances for different contexts
_file_operations_cache = {}

def get_file_operations(context: str = "general") -> FileOperations:
    """Get cached file operations instance for context"""
    if context not in _file_operations_cache:
        _file_operations_cache[context] = FileOperations(context)
    return _file_operations_cache[context]

# Convenience functions
def get_handler_file_operations() -> FileOperations:
    """Get file operations for File Handler context"""
    return get_file_operations("handler")

def get_workflow_file_operations() -> FileOperations:
    """Get file operations for Workflow Loader context"""
    return get_file_operations("workflow")