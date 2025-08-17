# Batch Processing

Gleitzeit provides batch processing capabilities for applying workflows to multiple files in parallel.

## Overview

Batch processing allows you to:
- Process multiple files with the same workflow
- Use glob patterns for file discovery
- Execute tasks in parallel with concurrency control
- Aggregate results across all files

## Basic Batch Workflow

### YAML Definition

```yaml
name: "Batch Text Analysis"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
  max_concurrent: 5
template:
  method: "llm/chat"
  parameters:
    model: "llama3.2"
    messages:
      - role: "user"
        content: "Summarize this document: ${file.content}"
```

### CLI Usage

```bash
# Basic batch processing
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize this document"

# With specific model
gleitzeit batch images --pattern "*.{jpg,png}" --model "llava:latest" --vision

# Save results
gleitzeit batch docs --pattern "*.md" --prompt "Extract key points" --output results.json
```

## BatchProcessor Class

The `BatchProcessor` handles file discovery and workflow creation:

```python
from gleitzeit.core.batch_processor import BatchProcessor

# Create processor
batch_processor = BatchProcessor()

# Scan directory for files
files = batch_processor.scan_directory("documents", "*.txt")

# Create batch workflow
workflow = batch_processor.create_batch_workflow(
    workflow_name="Document Analysis",
    files=files,
    method="llm/chat",
    model="llama3.2",
    prompt="Summarize: {content}",
    is_vision=False
)

# Process batch
result = await batch_processor.process_batch(
    directory="documents",
    pattern="*.txt",
    prompt="Summarize this document",
    model="llama3.2"
)
```

## File Discovery

### Glob Patterns

```python
# Basic patterns
"*.txt"           # All .txt files in directory
"*.{txt,md}"      # Multiple extensions
"**/*.txt"        # Recursive search (if supported)

# Examples
batch_processor.scan_directory("docs", "*.md")
batch_processor.scan_directory("images", "*.{jpg,png,gif}")
```

### File Handling

The batch processor:
1. **Scans directory** for matching files
2. **Reads file content** (text files) or encodes (images)
3. **Creates task** for each file
4. **Executes workflow** with all tasks

## Batch Results

### BatchResult Structure

```python
from gleitzeit.core.batch_processor import BatchResult

# Result contains:
batch_result = BatchResult(
    batch_id="batch_123",
    directory="documents",
    pattern="*.txt",
    total_files=10,
    successful_files=9,
    failed_files=1,
    results={
        "file1.txt": {"status": "completed", "response": "Summary..."},
        "file2.txt": {"status": "completed", "response": "Summary..."},
        "file3.txt": {"status": "failed", "error": "Timeout"}
    },
    processing_time=45.2
)
```

### Accessing Results

```python
# Get batch status
print(f"Processed {batch_result.successful_files}/{batch_result.total_files} files")
print(f"Success rate: {batch_result.get_success_rate():.1%}")

# Access individual results
for filename, result in batch_result.results.items():
    if result["status"] == "completed":
        print(f"{filename}: {result['response']}")
    else:
        print(f"{filename}: Failed - {result.get('error', 'Unknown')}")
```

## Python API

### Using GleitzeitClient

```python
from gleitzeit import GleitzeitClient

async with GleitzeitClient() as client:
    # Batch process files
    results = await client.batch_process(
        directory="documents",
        pattern="*.txt",
        prompt="Summarize this document",
        max_concurrent=5
    )
    
    # Process results
    for result in results:
        print(f"File: {result.file_name}")
        print(f"Summary: {result.response}")
```

## Supported File Types

### Text Files

```yaml
# Process text files
batch:
  directory: "texts"
  pattern: "*.{txt,md,py,js,yaml}"
template:
  method: "llm/chat"
  parameters:
    messages:
      - role: "user"
        content: "Analyze: ${file.content}"
```

### Image Files

```yaml
# Process images with vision model
batch:
  directory: "images"
  pattern: "*.{jpg,png,gif}"
template:
  method: "llm/vision"
  parameters:
    model: "llava:latest"
    messages:
      - role: "user"
        content: "Describe this image"
    image: "${file.content}"  # Base64 encoded
```

## Configuration

### Batch Processing Options

```yaml
# ~/.gleitzeit/config.yaml
batch:
  max_file_size: 1048576  # 1MB limit
  max_concurrent: 5       # Parallel tasks
  timeout_per_file: 30    # Seconds per file
```

### CLI Options

```bash
gleitzeit batch <directory> [options]

Options:
  --pattern TEXT          File pattern (e.g., "*.txt")
  --prompt TEXT          Processing prompt
  --model TEXT           LLM model to use
  --vision              Use vision model for images
  --max-concurrent INT   Parallel processing limit
  --output FILE         Save results to file
  --format TEXT         Output format (json|markdown)
```

## Examples

### Document Summarization

```bash
# Summarize all text documents
gleitzeit batch documents \
  --pattern "*.txt" \
  --prompt "Provide a 2-3 sentence summary" \
  --model "llama3.2" \
  --output summaries.json
```

### Image Analysis

```bash
# Analyze product images
gleitzeit batch product_images \
  --pattern "*.jpg" \
  --prompt "Describe the product in this image" \
  --model "llava:latest" \
  --vision \
  --output product_descriptions.json
```

### Code Analysis

```bash
# Analyze Python files
gleitzeit batch src \
  --pattern "*.py" \
  --prompt "List the main functions and their purposes" \
  --model "codellama" \
  --output code_analysis.json
```

## Error Handling

### Partial Failures

The batch processor continues processing even if some files fail:

```python
result = await batch_processor.process_batch(...)

if result.failed_files > 0:
    print(f"Warning: {result.failed_files} files failed")
    for filename, file_result in result.results.items():
        if file_result["status"] == "failed":
            print(f"  - {filename}: {file_result.get('error', 'Unknown error')}")
```

### Common Errors

- **File too large**: Files exceeding `max_file_size` are skipped
- **Unsupported format**: Binary files require special handling
- **Read permission**: Files without read access are skipped
- **Task timeout**: Individual file processing may timeout

## Best Practices

### File Organization

1. **Group similar files** in directories
2. **Use consistent naming** for easier pattern matching
3. **Keep files within size limits** for efficient processing

### Performance

1. **Tune concurrency**: Balance speed vs resource usage
2. **Set appropriate timeouts**: Based on file complexity
3. **Monitor memory usage**: Large files consume more memory

### Error Recovery

1. **Save intermediate results**: Use `--output` to save progress
2. **Handle failures gracefully**: Check success rates
3. **Retry failed files**: Process failed files separately if needed

## Limitations

Current batch processing implementation:
- Basic file discovery (no complex filtering)
- Simple templating (no conditional logic)
- Text and image files only (no complex formats)
- No streaming for large files
- No resume capability for interrupted batches

For more complex batch processing needs, consider writing custom workflows or using the Python API directly.