# Example Workflows

Copy-paste ready workflows using Ollama models and Python scripts.

## Basic Examples

### Simple Chat with Ollama
```yaml
name: "Chat"
tasks:
  - id: "chat"
    method: "llm/chat"
    parameters:
      model: "llama3.2"  # Ollama model
      messages:
        - role: "user"
          content: "Tell me a joke about programming"
```

### Q&A System
```yaml
name: "Q&A"
tasks:
  - id: "answer"
    method: "llm/chat"
    parameters:
      model: "mistral"  # Good for reasoning
      messages:
        - role: "system"
          content: "Answer questions accurately and concisely"
        - role: "user"
          content: "${input.question}"
```

## Document Processing

### Document Summarizer with Python Scripts

First, create `read_file.py`:
```python
import sys
import json

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
filename = args.get('filename', 'document.txt')

try:
    with open(filename, 'r') as f:
        content = f.read()
    print(json.dumps({"content": content, "length": len(content)}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
```

Then use in workflow:
```yaml
name: "Document Summarizer"
tasks:
  - id: "read_file"
    method: "python/execute"
    parameters:
      script: "read_file.py"
      args:
        filename: "document.txt"
  
  - id: "summarize"
    method: "llm/chat"
    dependencies: ["read_file"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Summarize this document in 3 bullet points:
            ${read_file.content}
```

### Batch File Processor
```yaml
name: "Batch Analyzer"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
  output: "analysis"
  max_concurrent: 5
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: |
        Analyze this document:
        1. Main topic
        2. Key points (5 bullets)
        3. Sentiment
        
        Document: ${file_content}
```

## Data Analysis

### CSV Data Analyzer

Create `analyze_csv.py`:
```python
import sys
import json
import csv

args = json.loads(sys.argv[1])
csv_file = args.get('file', 'data.csv')

try:
    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        data = list(reader)
    
    # Basic analysis
    row_count = len(data)
    columns = list(data[0].keys()) if data else []
    
    # Try to calculate numeric stats
    numeric_cols = {}
    for col in columns:
        try:
            values = [float(row[col]) for row in data if row[col]]
            if values:
                numeric_cols[col] = {
                    "min": min(values),
                    "max": max(values),
                    "avg": sum(values) / len(values)
                }
        except:
            pass
    
    result = {
        "row_count": row_count,
        "columns": columns,
        "numeric_stats": numeric_cols,
        "sample_data": data[:5] if len(data) > 5 else data
    }
    
    print(json.dumps(result))
except Exception as e:
    print(json.dumps({"error": str(e)}))
```

Workflow:
```yaml
name: "CSV Analysis"
tasks:
  - id: "load_data"
    method: "python/execute"
    parameters:
      script: "analyze_csv.py"
      args:
        file: "sales.csv"
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["load_data"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: |
            Analyze this data and provide insights:
            ${load_data}
            
            Include:
            - Key trends
            - Anomalies
            - Recommendations
  
  - id: "save_report"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "save_report.py"
      args:
        content: "${analyze.response}"
        filename: "analysis_report.md"
```

## Content Generation

### Blog Post Generator
```yaml
name: "Blog Generator"
tasks:
  - id: "research"
    method: "llm/chat"
    parameters:
      model: "mistral"  # Good for creative content
      messages:
        - role: "user"
          content: "Research and list 5 key points about ${input.topic}"
  
  - id: "outline"
    method: "llm/chat"
    dependencies: ["research"]
    parameters:
      model: "mistral"
      messages:
        - role: "user"
          content: |
            Create a blog post outline based on these points:
            ${research.response}
            
            Include: Introduction, 3 main sections, conclusion
  
  - id: "write"
    method: "llm/chat"
    dependencies: ["outline"]
    parameters:
      model: "mistral"
      temperature: 0.8  # More creative
      messages:
        - role: "system"
          content: "You are a professional blog writer"
        - role: "user"
          content: |
            Write a 500-word blog post following this outline:
            ${outline.response}
  
  - id: "save"
    method: "python/execute"
    dependencies: ["write"]
    parameters:
      script: "save_blog.py"
      args:
        content: "${write.response}"
        topic: "${input.topic}"
```

## Code Analysis

### Code Reviewer

Create `read_python_files.py`:
```python
import sys
import json
import glob
import os

args = json.loads(sys.argv[1])
pattern = args.get('pattern', '*.py')
directory = args.get('directory', '.')

files = {}
for path in glob.glob(os.path.join(directory, pattern)):
    try:
        with open(path, 'r') as f:
            files[path] = f.read()
    except:
        pass

print(json.dumps({"files": files, "count": len(files)}))
```

Workflow:
```yaml
name: "Code Review"
tasks:
  - id: "read_code"
    method: "python/execute"
    parameters:
      script: "read_python_files.py"
      args:
        directory: "src"
        pattern: "**/*.py"
  
  - id: "review"
    method: "llm/chat"
    dependencies: ["read_code"]
    parameters:
      model: "codellama"  # Specialized for code
      messages:
        - role: "system"
          content: "You are an expert Python code reviewer"
        - role: "user"
          content: |
            Review this Python code for:
            - Bugs
            - Security issues
            - Performance problems
            - Best practices
            
            Code files: ${read_code.files}
```

## Image Analysis (with Ollama Vision Models)

### Image Analyzer
```yaml
name: "Image Analysis"
tasks:
  - id: "analyze_image"
    method: "llm/vision"
    parameters:
      model: "llava"  # Ollama vision model
      messages:
        - role: "user"
          content: "Describe this image in detail"
      images:
        - "path/to/image.jpg"
```

### Batch Image Processing
```yaml
name: "Image Batch Processor"
type: "batch"
batch:
  directory: "images"
  pattern: "*.jpg"
  output: "descriptions"
template:
  method: "llm/vision"
  model: "llava"
  messages:
    - role: "user"
      content: |
        Analyze this image:
        1. What is shown?
        2. Key objects
        3. Colors and composition
        4. Suggested caption
```

## Advanced Workflows

### Multi-Model Pipeline
```yaml
name: "Multi-Model Analysis"
tasks:
  - id: "quick_analysis"
    method: "llm/chat"
    parameters:
      model: "llama3.2"  # Fast model for initial analysis
      messages:
        - role: "user"
          content: "Quick analysis of: ${input.text}"
  
  - id: "detailed_analysis"
    method: "llm/chat"
    parameters:
      model: "mistral"  # More capable model
      messages:
        - role: "user"
          content: "Detailed analysis of: ${input.text}"
  
  - id: "code_suggestions"
    method: "llm/chat"
    parameters:
      model: "codellama"  # Code-specific model
      messages:
        - role: "user"
          content: "Suggest code improvements for: ${input.text}"
  
  - id: "combine_results"
    method: "python/execute"
    dependencies: ["quick_analysis", "detailed_analysis", "code_suggestions"]
    parameters:
      script: "combine_analyses.py"
      args:
        quick: "${quick_analysis.response}"
        detailed: "${detailed_analysis.response}"
        code: "${code_suggestions.response}"
```

### Parallel Processing
```yaml
name: "Parallel Tasks"
tasks:
  # These three run in parallel (no dependencies)
  - id: "task1"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - content: "Process A"
  
  - id: "task2"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - content: "Process B"
  
  - id: "task3"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - content: "Process C"
  
  # This waits for all three
  - id: "combine"
    method: "python/execute"
    dependencies: ["task1", "task2", "task3"]
    parameters:
      script: "combine.py"
      args:
        results:
          - "${task1.response}"
          - "${task2.response}"
          - "${task3.response}"
```

## Running Examples

### From CLI
```bash
# Run a workflow
gleitzeit run blog_generator.yaml --input topic="AI Safety"

# Batch process
gleitzeit batch documents --pattern "*.txt" --prompt "Summarize" --model llama3.2

# With custom scripts directory
gleitzeit run workflow.yaml --scripts-dir ./my_scripts
```

### From Python
```python
from gleitzeit import Client
import asyncio

async def run_examples():
    async with Client() as client:
        # Run workflow with inputs
        result = await client.run_workflow(
            "blog_generator.yaml",
            inputs={"topic": "Machine Learning"}
        )
        
        # Get specific task output
        blog_content = result["write"]["response"]
        
        # Batch process with specific model
        summaries = await client.batch_process(
            directory="reports",
            pattern="*.txt",
            prompt="Summarize in 3 sentences",
            model="llama3.2"
        )

asyncio.run(run_examples())
```

## Python Script Best Practices

### Script Template
```python
#!/usr/bin/env python3
import sys
import json
import traceback

def main(args):
    """Main processing logic"""
    try:
        # Your code here
        result = process(args)
        return {"status": "success", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def process(args):
    """Process the input arguments"""
    # Your processing logic
    return "processed_data"

if __name__ == "__main__":
    # Parse arguments
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    
    # Run main function
    result = main(args)
    
    # Output as JSON
    print(json.dumps(result))
```

## Tips

1. **Model Selection** - Choose the right Ollama model:
   - `llama3.2` - Fast, general purpose
   - `mistral` - Better reasoning
   - `codellama` - Code generation/review
   - `llava` - Image understanding
   
2. **Python Scripts** - Always:
   - Accept args as JSON via `sys.argv[1]`
   - Return results as JSON via `print(json.dumps(...))`
   - Handle errors gracefully
   
3. **Parallel Execution** - Tasks without dependencies run in parallel

4. **File Paths** - Use relative paths from workflow directory

5. **Testing** - Test scripts independently:
   ```bash
   python script.py '{"arg1": "value1"}'
   ```