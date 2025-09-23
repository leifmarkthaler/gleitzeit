#!/usr/bin/env python3
"""
Analysis and fix for clashes between file handler and workflow loader.
"""

from pathlib import Path

def analyze_clashes():
    """Analyze the clashes between file handler and workflow loader"""

    print("=" * 60)
    print("FILE HANDLER vs WORKFLOW LOADER CLASH ANALYSIS")
    print("=" * 60)

    clashes = [
        {
            'category': 'Error Codes',
            'conflicts': [
                'Both use similar error scenarios but different codes',
                'Workflow loader: FILE_SYSTEM_ERROR (-23002)',
                'File handler: FILE_NOT_FOUND (-22001)',
                'Potential confusion for retry system'
            ]
        },
        {
            'category': 'Security Validation',
            'conflicts': [
                'Both implement _validate_file_path() methods',
                'Workflow loader: ConfigurationError for path traversal',
                'File handler: FILE_SECURITY_VIOLATION error',
                'Different error types for same violation'
            ]
        },
        {
            'category': 'File Size Limits',
            'conflicts': [
                'Workflow loader: MAX_WORKFLOW_SIZE_MB = 100MB',
                'File handler: MAX_FILE_SIZE_MB = 50MB',
                'Inconsistent size limits for file operations',
                'Different error handling for oversized files'
            ]
        },
        {
            'category': 'Path Validation',
            'conflicts': [
                'Workflow loader: ALLOWED_PATH_PREFIXES configuration',
                'File handler: Security validation in _validate_file_path',
                'Different approaches to path restriction',
                'Could conflict when loading workflow files'
            ]
        },
        {
            'category': 'Error Exception Types',
            'conflicts': [
                'Workflow loader: Uses ConfigurationError, WorkflowValidationError',
                'File handler: Uses GleitzeitError with specific error codes',
                'Inconsistent error handling patterns',
                'Retry system expects consistent error classification'
            ]
        }
    ]

    for i, clash in enumerate(clashes, 1):
        print(f"\n{i}. {clash['category']}")
        print("-" * 40)
        for conflict in clash['conflicts']:
            print(f"   • {conflict}")

    print(f"\n{'=' * 60}")
    print("RECOMMENDED SOLUTIONS")
    print("=" * 60)

    solutions = [
        {
            'title': 'Unified Error Handling',
            'actions': [
                'Use FILE_SYSTEM_ERROR for workflow loader file operations',
                'Keep FILE_* specific codes for file handler',
                'Map workflow loader errors to central error codes',
                'Ensure consistent error metadata for retry system'
            ]
        },
        {
            'title': 'Shared Security Validation',
            'actions': [
                'Create common file security validator in core module',
                'Both components use same validation logic',
                'Consistent error types for security violations',
                'Centralized path traversal detection'
            ]
        },
        {
            'title': 'Configuration Alignment',
            'actions': [
                'Workflow loader inherits file size limits from file handler',
                'Or create shared file operation configuration',
                'Consistent size limits across file operations',
                'Unified allowed paths configuration'
            ]
        },
        {
            'title': 'Clear Separation of Concerns',
            'actions': [
                'Workflow loader: Only workflow files (YAML/JSON/Python)',
                'File handler: General file operations (content loading)',
                'Workflow loader could use file handler for loading',
                'Avoid duplicate file operation logic'
            ]
        }
    ]

    for i, solution in enumerate(solutions, 1):
        print(f"\n{i}. {solution['title']}")
        print("-" * 40)
        for action in solution['actions']:
            print(f"   ✓ {action}")

def create_unified_validator():
    """Create a unified file validator to resolve clashes"""

    print(f"\n{'=' * 60}")
    print("UNIFIED FILE VALIDATOR IMPLEMENTATION")
    print("=" * 60)

    validator_code = '''
# /src/gleitzeit/core/file_validator.py

from pathlib import Path
from typing import List, Optional
from .errors import GleitzeitError, ErrorCode

class FileValidationConfig:
    """Shared configuration for file validation"""

    # Size limits
    MAX_FILE_SIZE_MB = 50  # Default for file handler
    MAX_WORKFLOW_SIZE_MB = 100  # Specific for workflow files

    # Security
    ALLOWED_PATH_PREFIXES: List[str] = []
    BLOCKED_EXTENSIONS = ['.exe', '.dll', '.so', '.dylib', '.app']

    @classmethod
    def from_env(cls):
        """Load from environment variables"""
        import os
        config = cls()
        if max_file := os.getenv('GLEITZEIT_MAX_FILE_SIZE_MB'):
            config.MAX_FILE_SIZE_MB = int(max_file)
        if max_workflow := os.getenv('GLEITZEIT_MAX_WORKFLOW_SIZE_MB'):
            config.MAX_WORKFLOW_SIZE_MB = int(max_workflow)
        if allowed_paths := os.getenv('GLEITZEIT_ALLOWED_PATHS'):
            config.ALLOWED_PATH_PREFIXES = allowed_paths.split(',')
        return config

class UnifiedFileValidator:
    """Unified file validation for both workflow loader and file handler"""

    def __init__(self, config: Optional[FileValidationConfig] = None):
        self.config = config or FileValidationConfig.from_env()

    def validate_file_path(self, path: Path, context: str = "file") -> None:
        """Validate file path with context (file handler vs workflow loader)"""

        # Check for path traversal
        if ".." in str(path):
            raise GleitzeitError(
                f"Path traversal detected: {path}",
                code=ErrorCode.FILE_SECURITY_VIOLATION,
                data={'path': str(path), 'context': context}
            )

        # Check allowed paths
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
                    data={'path': str(abs_path), 'context': context}
                )

        # Check blocked extensions
        ext = path.suffix.lower()
        if ext in self.config.BLOCKED_EXTENSIONS:
            raise GleitzeitError(
                f"Blocked file type: {ext}",
                code=ErrorCode.FILE_SECURITY_VIOLATION,
                data={'path': str(path), 'extension': ext, 'context': context}
            )

    def validate_file_size(self, path: Path, context: str = "file") -> None:
        """Validate file size based on context"""

        if not path.exists():
            raise GleitzeitError(
                f"File not found: {path}",
                code=ErrorCode.FILE_NOT_FOUND,
                data={'path': str(path), 'context': context}
            )

        try:
            file_size_mb = path.stat().st_size / (1024 * 1024)
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
                data={'path': str(path), 'context': context, 'os_error': str(e)}
            )

        # Choose size limit based on context
        if context == "workflow":
            max_size = self.config.MAX_WORKFLOW_SIZE_MB
        else:
            max_size = self.config.MAX_FILE_SIZE_MB

        if file_size_mb > max_size:
            raise GleitzeitError(
                f"File too large: {path} ({file_size_mb:.2f}MB > {max_size}MB)",
                code=ErrorCode.FILE_TOO_LARGE,
                data={
                    'path': str(path),
                    'size_mb': file_size_mb,
                    'max_mb': max_size,
                    'context': context
                }
            )

# Global validator instance
_file_validator = None

def get_file_validator() -> UnifiedFileValidator:
    """Get shared file validator instance"""
    global _file_validator
    if _file_validator is None:
        _file_validator = UnifiedFileValidator()
    return _file_validator
'''

    print("Unified validator code:")
    print(validator_code)

def show_updated_usage():
    """Show how both components would use the unified validator"""

    print(f"\n{'=' * 60}")
    print("UPDATED COMPONENT USAGE")
    print("=" * 60)

    file_handler_usage = '''
# File Handler Usage:
from gleitzeit.core.file_validator import get_file_validator

class FileHandler(BaseHandler):
    def __init__(self, config):
        super().__init__(config)
        self.file_validator = get_file_validator()

    async def _load_file(self, task):
        path = Path(task.params['path'])

        # Use unified validation
        self.file_validator.validate_file_path(path, context="file")
        self.file_validator.validate_file_size(path, context="file")

        # Continue with file loading...
'''

    workflow_loader_usage = '''
# Workflow Loader Usage:
from gleitzeit.core.file_validator import get_file_validator

class WorkflowLoaderWorkerV2(BaseWorker):
    def __init__(self, config):
        super().__init__(config)
        self.file_validator = get_file_validator()

    async def load_workflow_from_path(self, path: str, format: Optional[str] = None):
        file_path = Path(path)

        # Use unified validation
        self.file_validator.validate_file_path(file_path, context="workflow")
        self.file_validator.validate_file_size(file_path, context="workflow")

        # Continue with workflow loading...
'''

    print("1. File Handler:")
    print(file_handler_usage)
    print("\n2. Workflow Loader:")
    print(workflow_loader_usage)

    print(f"\n{'=' * 60}")
    print("BENEFITS OF UNIFIED APPROACH")
    print("=" * 60)

    benefits = [
        "✓ Consistent error codes and messages",
        "✓ Shared security validation logic",
        "✓ Unified configuration management",
        "✓ Better retry system compatibility",
        "✓ Reduced code duplication",
        "✓ Easier maintenance and testing",
        "✓ Clear separation of concerns"
    ]

    for benefit in benefits:
        print(f"  {benefit}")

if __name__ == "__main__":
    analyze_clashes()
    create_unified_validator()
    show_updated_usage()