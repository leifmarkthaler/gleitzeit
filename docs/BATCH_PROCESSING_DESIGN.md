# Batch Processing Design Document

## Overview
Add batch processing capabilities to Gleitzeit v0.0.4 for processing multiple files (text, images) in a single operation.

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

### 2. Provider Updates
```python
class OllamaProvider:
    async def _handle_batch(self, params):
        """Process multiple files"""
        files = params.get('files', [])
        directory = params.get('directory')
        pattern = params.get('file_pattern', '*')
        
        # Collect files
        if directory:
            files.extend(self._scan_directory(directory, pattern))
        
        # Process each file
        results = {}
        for file_path in files:
            try:
                result = await self._process_single_file(file_path, params)
                results[file_path] = {'status': 'success', 'result': result}
            except Exception as e:
                results[file_path] = {'status': 'failed', 'error': str(e)}
        
        return results
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

### Phase 1: Core Batch Support ✅ (This PR)
- [ ] Update LLM protocol to accept `files` array
- [ ] Update Ollama provider to handle multiple files
- [ ] Create BatchResult model
- [ ] Add basic `gleitzeit batch` command

### Phase 2: Directory Scanning
- [ ] Add directory scanning with patterns
- [ ] Support recursive directory traversal
- [ ] Add file filtering by size/date

### Phase 3: Workflow Generation
- [ ] Implement `gleitzeit generate batch` command
- [ ] Create workflow templates for batch processing
- [ ] Add customization options

### Phase 4: Results Management
- [ ] Implement batch result storage
- [ ] Add batch-list, batch-show commands
- [ ] Add export functionality
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

### Batch Document Analysis
```yaml
name: "Batch Document Analysis"
tasks:
  - name: "analyze_all_documents"
    protocol: "llm/v1"
    method: "llm/chat"
    params:
      model: "llama3.2:latest"
      directory: "examples/documents"
      file_pattern: "*.txt"
      messages:
        - role: "user"
          content: "Provide a 2-sentence summary of this document"
```

### Batch Image Description
```yaml
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