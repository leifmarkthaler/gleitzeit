# Batch Processing Quick Reference

## Dynamic Batch Workflows (Recommended)

### Text Files
```yaml
name: "Batch Text Processing"
type: "batch"
batch:
  directory: "path/to/documents"
  pattern: "*.txt"  # or "*.md", "*.log", etc.
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Your prompt here"
```

### Image Files
```yaml
name: "Batch Image Processing"
type: "batch"
batch:
  directory: "path/to/images"
  pattern: "*.png"  # or "*.jpg", "*.jpeg", etc.
template:
  method: "llm/vision"
  model: "llava:latest"
  messages:
    - role: "user"
      content: "Describe this image"
```

### Mixed Pattern Examples
```yaml
# Process all Python files
pattern: "*.py"

# Process all test files
pattern: "test_*.txt"

# Process all files (use carefully!)
pattern: "*"

# Process specific prefixes
pattern: "report_*.pdf"
```

## CLI Batch Command

```bash
# Basic usage
gleitzeit batch <directory> --pattern "*.txt" --prompt "Summarize this"

# With specific model
gleitzeit batch ./docs --pattern "*.md" --model llama3.2 --prompt "Extract key points"

# For images
gleitzeit batch ./images --pattern "*.png" --prompt "Describe" --vision

# Save output
gleitzeit batch ./data --pattern "*.csv" --prompt "Analyze" --output results.json
```

## How It Works

1. **File Discovery**: System scans the specified directory for files matching the pattern
2. **Task Generation**: Creates a parallel task for each discovered file
3. **Preprocessing**: 
   - Text files: Content is read and appended to the prompt
   - Images: Converted to base64 and passed to vision models
4. **Parallel Execution**: All files are processed simultaneously for speed
5. **Result Collection**: Results are collected and displayed/saved

## Key Benefits

- **No Manual File Lists**: Files are discovered automatically
- **Scalable**: Works with 1 or 1000 files
- **Type-Agnostic**: Same workflow structure for text and images
- **Provider-Independent**: Works with any LLM provider
- **Efficient**: Parallel processing for optimal performance

## Example Use Cases

### Document Summarization
```yaml
name: "Summarize Meeting Notes"
type: "batch"
batch:
  directory: "meetings/2024"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "system"
      content: "You are a meeting notes summarizer"
    - role: "user"
      content: "Extract action items and key decisions from this meeting"
```

### Image Cataloging
```yaml
name: "Catalog Product Images"
type: "batch"
batch:
  directory: "products/images"
  pattern: "*.jpg"
template:
  method: "llm/vision"
  model: "llava:latest"
  messages:
    - role: "user"
      content: "Describe this product image including color, style, and key features"
```

### Code Analysis
```yaml
name: "Analyze Python Files"
type: "batch"
batch:
  directory: "src"
  pattern: "*.py"
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Review this code for potential bugs and suggest improvements"
```

## Tips

1. **Test with Small Sets**: Start with a limited pattern to test your prompt
2. **Use Specific Patterns**: Avoid `*` unless you really want all files
3. **Check File Sizes**: Large files may take longer to process
4. **Monitor Progress**: Use the CLI output to track processing status
5. **Save Results**: Use `--output` flag for important batch runs