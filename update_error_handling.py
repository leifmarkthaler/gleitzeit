#!/usr/bin/env python3
"""
Script to update remaining files to use centralized error handling
"""

import re
from pathlib import Path

# Define file updates
FILE_UPDATES = {
    # Phase 2: Core Files
    "src/gleitzeit/core/workflow_loader.py": [
        ("raise ValueError(", "raise WorkflowValidationError(workflow.id if workflow else 'unknown', ["),
    ],
    "src/gleitzeit/core/batch_processor.py": [
        ("raise ValueError(", "raise TaskValidationError('batch_task', ["),
    ],
    "src/gleitzeit/core/models.py": [
        ("raise ValueError(", "raise TaskValidationError(self.id if hasattr(self, 'id') else 'unknown', ["),
    ],
    "src/gleitzeit/core/execution_engine.py": [
        ("raise ValueError(", "raise WorkflowValidationError(workflow.id if workflow else 'unknown', ["),
    ],
    "src/gleitzeit/core/jsonrpc.py": [
        ("raise ValueError(", "raise ProtocolError("),
    ],
    
    # Phase 3: Support Files
    "src/gleitzeit/registry.py": [
        ("raise ValueError(", "raise ProviderNotFoundError("),
    ],
    "src/gleitzeit/protocol.py": [
        ("raise ValueError(", "raise ProtocolError("),
    ],
    "src/gleitzeit/task_queue.py": [
        ("raise ValueError(", "raise QueueNotFoundError("),
    ],
    "src/gleitzeit/workflow_manager.py": [
        ("raise ValueError(", "raise WorkflowValidationError(workflow_id if 'workflow_id' in locals() else 'unknown', ["),
    ],
    
    # Phase 4: CLI Files
    "src/gleitzeit/cli/workflow.py": [
        ("raise ValueError(", "raise ConfigurationError("),
    ],
    "src/gleitzeit/cli/commands/dev.py": [
        ("raise Exception(", "raise TaskError("),
        ("except:", "except Exception:"),  # Fix bare except
    ],
    "src/gleitzeit/client/api.py": [
        ("raise ValueError(", "raise TaskValidationError('api_task', ["),
    ],
}

def update_file(file_path: Path, replacements: list):
    """Update a single file with error handling replacements"""
    if not file_path.exists():
        print(f"⚠️  File not found: {file_path}")
        return False
    
    content = file_path.read_text()
    original_content = content
    
    for old_pattern, new_pattern in replacements:
        # Count occurrences
        count = content.count(old_pattern)
        if count > 0:
            print(f"  Found {count} occurrences of '{old_pattern[:30]}...'")
            # For now, just show what would be replaced
            # In production, would do: content = content.replace(old_pattern, new_pattern)
    
    if content != original_content:
        # file_path.write_text(content)
        print(f"  ✓ Would update {file_path.name}")
        return True
    return False

def main():
    """Main update function"""
    print("🔧 Error Handling Update Script")
    print("=" * 50)
    
    base_path = Path(__file__).parent
    
    for file_rel_path, replacements in FILE_UPDATES.items():
        file_path = base_path / file_rel_path
        print(f"\n📄 Checking: {file_rel_path}")
        
        if update_file(file_path, replacements):
            print(f"  ✅ Updates needed")
        else:
            print(f"  ⏭️  No updates needed or file not found")
    
    print("\n" + "=" * 50)
    print("✅ Analysis complete!")
    print("\nNote: This is a dry run. Actual replacements need more context-aware updates.")

if __name__ == "__main__":
    main()