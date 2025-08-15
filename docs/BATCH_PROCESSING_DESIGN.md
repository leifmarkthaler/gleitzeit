# Batch Processing Design Document

## Overview
Add batch processing capabilities to Gleitzeit v0.0.4 for processing multiple files (text, images) in a single operation.

## Key Features (NEW)

### Dynamic Batch Workflows
- **Automatic File Discovery**: Workflows can discover files at runtime using directory and glob patterns
- **Template-Based Processing**: Define a single task template that gets applied to all discovered files
- **Universal Provider Support**: Works with any provider through base provider preprocessing
- **File Type Detection**: Automatically handles text vs image files based on extension

### Implementation Highlights
1. **No Provider Changes Required**: Batch processing works through base provider preprocessing
2. **YAML Workflow Support**: Simple YAML syntax with `type: "batch"` for dynamic workflows  
3. **Backward Compatible**: Existing static batch workflows continue to work
4. **Parallel Execution**: Files are processed as parallel tasks for optimal performance

## CLI Commands

### 1. Basic Batch Command
```bash
# Process directory
gleitzeit batch <directory> --pattern "*.txt" --prompt "Summarize this document"

# Process specific files
gleitzeit batch --files file1.txt file2.txt file3.txt --prompt "Analyze"

# Process images
gleitzeit batch ./images --pattern "*.png" --prompt "Describe this image" --vision
```

### 2. Batch Generation Command
```bash
# Generate workflow from directory
gleitzeit generate batch <directory> [--output workflow.yaml]

# Generate from file list
gleitzeit generate batch --files file1.txt file2.txt [--output workflow.yaml]
```

### 3. Batch Management Commands
```bash
# List batch jobs
gleitzeit batch-list

# Show batch results
gleitzeit batch-show <batch-id>

# Resume failed items
gleitzeit batch-resume <batch-id>

# Export results
gleitzeit batch-export <batch-id> --format [json|csv|markdown]
```

## Internal Architecture

### 1. Protocol Updates
- Add `files` parameter (array) to `llm/chat` and `llm/vision` methods
- Add `directory` and `file_pattern` parameters for directory scanning

### 2. Base Provider Updates (NEW)
The base provider now handles universal file discovery and preprocessing:

```python
# In providers/base.py
async def _preprocess_params(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Pre-process parameters to handle file discovery"""
    processed = copy.deepcopy(params)
    
    # Handle directory + file_pattern for batch processing
    if 'directory' in processed and 'file_pattern' in processed:
        directory = processed.pop('directory')
        file_pattern = processed.pop('file_pattern')
        
        # Discover files matching the pattern
        pattern_path = Path(directory) / file_pattern
        matching_files = glob.glob(str(pattern_path))
        
        # Add discovered files to the files list
        if 'files' not in processed:
            processed['files'] = []
        processed['files'].extend(matching_files)
    
    # Handle file_path preprocessing (reads file content)
    # Handle image_path preprocessing (converts to base64)
    return processed
```

### 3. Workflow Loader Updates (NEW)
The workflow loader now supports dynamic batch workflows:

```python
# In workflow_loader.py
def load_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    # Check if this is a batch workflow
    if data.get('type') == 'batch' or 'batch' in data:
        return create_batch_workflow_from_dict(data)
    # ... regular workflow processing

def create_batch_workflow_from_dict(data: Dict[str, Any]) -> Workflow:
    """Create a batch workflow with dynamic file discovery"""
    batch_config = data.get('batch', {})
    template = data.get('template', {})
    
    # Discover files
    files = glob.glob(str(Path(directory) / pattern))
    
    # Create tasks for each file
    tasks = []
    for file_path in files:
        task = create_task_from_template(template, file_path)
        tasks.append(task)
    
    return Workflow(tasks=tasks, ...)
```

### 3. Batch Result Storage
```python
class BatchResult:
    batch_id: str
    created_at: datetime
    total_files: int
    successful: int
    failed: int
    results: Dict[str, Any]
    parameters: Dict[str, Any]
```

## Implementation Phases

### Phase 1: Core Batch Support ✅ (Completed)
- [x] Update LLM protocol to accept `files` array
- [x] Update base provider to handle directory/file_pattern preprocessing
- [x] Create BatchResult model
- [x] Add basic `gleitzeit batch` command

### Phase 2: Directory Scanning ✅ (Completed)
- [x] Add directory scanning with patterns
- [x] Support glob patterns for file discovery
- [x] Add file filtering by extension

### Phase 3: Dynamic Batch Workflows ✅ (Completed)
- [x] Implement dynamic batch workflow support in YAML
- [x] Create workflow templates for batch processing
- [x] Add automatic file discovery from directory/pattern

### Phase 4: Results Management (Partial)
- [x] Implement batch result storage
- [ ] Add batch-list, batch-show commands
- [x] Add export functionality (JSON, Markdown)
- [ ] Implement resume capability

## Data Flow

```
1. User runs: gleitzeit batch ./docs --pattern "*.txt" --prompt "Summarize"
2. CLI scans directory for matching files
3. Creates batch job with unique ID
4. For each file:
   a. Read file content
   b. Send to LLM with prompt
   c. Store result
   d. Update progress
5. Save batch results to persistence
6. Display summary to user
```

## Error Handling

- **File not found**: Skip and log, continue with other files
- **File too large**: Skip files over configurable limit (default 1MB)
- **LLM timeout**: Retry with exponential backoff, mark as failed after 3 attempts
- **Invalid file format**: Log error, skip file
- **Partial batch failure**: Save successful results, allow resume for failed items

## Output Formats

### JSON Format
```json
{
  "batch_id": "batch_2024-11-15_14-30-00",
  "parameters": {
    "prompt": "Summarize this document",
    "model": "llama3.2",
    "directory": "./documents"
  },
  "summary": {
    "total": 5,
    "successful": 4,
    "failed": 1,
    "processing_time": 23.5
  },
  "results": [
    {
      "file": "document1.txt",
      "status": "success",
      "result": "Summary content...",
      "processing_time": 2.3
    }
  ]
}
```

### Markdown Format
```markdown
# Batch Processing Results
**Batch ID**: batch_2024-11-15_14-30-00  
**Date**: 2024-11-15 14:30:00  
**Total Files**: 5 (4 successful, 1 failed)

## Results

### ✅ document1.txt
Summary content...

### ✅ document2.txt
Summary content...

### ❌ document3.txt
Error: File too large
```

### CSV Format
```csv
file,status,result,processing_time,error
document1.txt,success,"Summary content...",2.3,
document2.txt,success,"Summary content...",1.8,
document3.txt,failed,,0.0,File too large
```

## Configuration

Add to `.gleitzeit/config.yaml`:
```yaml
batch:
  max_file_size: 1048576  # 1MB
  max_concurrent: 5
  timeout_per_file: 30
  retry_attempts: 3
  default_pattern: "*"
  results_directory: "~/.gleitzeit/batch_results"
```

## Progress Display

```
Batch Processing: Scientific Papers Analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 80% 4/5 files

Currently processing:
  ⏳ paper4.pdf (15s)

Completed:
  ✅ paper1.pdf - Quantum computing breakthrough... (2.3s)
  ✅ paper2.pdf - Machine learning in medicine... (3.1s)
  ✅ paper3.pdf - Climate change mitigation... (2.8s)

Queued:
  ⏸  paper5.pdf

Elapsed: 23s | ETA: 6s
```

## Example Workflows

### Dynamic Batch Document Analysis with LLM
```yaml
# Dynamic batch workflow with automatic file discovery
name: "Dynamic Batch Text Analysis"
description: "Dynamically discover and analyze text documents"
type: "batch"  # Indicates this is a batch workflow

# Batch configuration - discovers files at runtime
batch:
  directory: "examples/documents"
  pattern: "*.txt"  # Glob pattern for file discovery
  
# Template task to apply to each discovered file
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "system"
      content: "You are a helpful document analyzer."
    - role: "user"
      content: "Provide a 2-sentence summary of this document"
```

### Dynamic Batch Processing with Python Scripts
```yaml
# Process files using Python scripts
name: "Python Batch File Processing"
description: "Process multiple files using Python script"
type: "batch"
protocol: "python/v1"  # Specify Python protocol

batch:
  directory: "examples/documents"
  pattern: "*.txt"

template:
  method: "python/execute"
  file: "examples/scripts/read_text_file.py"  # Python script to execute
  timeout: 10
  # File paths are automatically passed to the script via context
```

### Dynamic Batch Image Analysis (NEW)
```yaml
name: "Dynamic Batch Image Analysis"
description: "Dynamically discover and analyze images"
type: "batch"

batch:
  directory: "examples/images"
  pattern: "*.png"  # Will find all PNG images
  
template:
  method: "llm/vision"
  model: "llava:latest"
  messages:
    - role: "user"
      content: "Describe what you see in this image in detail."
```

### Static Batch Processing (Legacy)
```yaml
# Static batch with predefined file list
name: "Batch Image Processing"
tasks:
  - name: "describe_images"
    protocol: "llm/v1"
    method: "llm/vision"
    params:
      model: "llava:latest"
      files:
        - "examples/images/test_colors.png"
        - "examples/images/sales_chart.png"
      messages:
        - role: "user"
          content: "Describe what you see in this image"
```

## Success Criteria

1. Can process 10+ files in a single command
2. Provides clear progress feedback
3. Handles failures gracefully
4. Results are easily accessible and exportable
5. Performance: <5s overhead for batch of 10 files
6. Memory efficient: Streams files, doesn't load all at once