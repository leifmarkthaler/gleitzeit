# Workflows

## Workflow Structure

A workflow is a YAML file that defines tasks and their execution order.

### Basic Structure

```yaml
name: "Workflow Name"
description: "Optional description"
version: "1.0.0"
tasks:
  - id: "task_id"
    method: "protocol/method"
    parameters:
      # Task-specific parameters
```

### Complete Example

```yaml
name: "Document Analysis"
description: "Analyze and summarize documents"
version: "1.0.0"

tasks:
  - id: "read_file"
    method: "python/execute"
    parameters:
      script: "read_document.py"
      args:
        file: "report.txt"
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["read_file"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "system"
          content: "You are a document analyst"
        - role: "user"
          content: "Analyze: ${read_file.content}"
  
  - id: "save_summary"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "save_summary.py"
      args:
        content: "${analyze.response}"
        output: "summary.md"
```

## Task Configuration

### Required Fields

- **id**: Unique identifier for the task
- **method**: Protocol method to execute

### Optional Fields

- **dependencies**: List of task IDs that must complete first
- **retry**: Retry configuration
- **timeout**: Task timeout in seconds
- **parameters**: Method-specific parameters

### Retry Configuration

```yaml
tasks:
  - id: "resilient_task"
    method: "llm/chat"
    retry:
      max_attempts: 3        # Number of retry attempts
      delay: 2               # Initial delay in seconds
      exponential_backoff: true  # Double delay each retry
      max_delay: 30          # Maximum delay between retries
```

## Dependencies

### Linear Dependencies

Tasks execute in sequence:

```yaml
tasks:
  - id: "step1"
    method: "llm/chat"
  
  - id: "step2"
    dependencies: ["step1"]
    method: "llm/chat"
  
  - id: "step3"
    dependencies: ["step2"]
    method: "llm/chat"
```

### Multiple Dependencies

Task waits for all dependencies:

```yaml
tasks:
  - id: "data1"
    method: "python/execute"
  
  - id: "data2"
    method: "python/execute"
  
  - id: "combine"
    dependencies: ["data1", "data2"]
    method: "python/execute"
```

### Complex Dependency Graph

```yaml
tasks:
  # Parallel initial tasks
  - id: "fetch_data"
    method: "python/execute"
  
  - id: "fetch_config"
    method: "python/execute"
  
  # Process after data is ready
  - id: "process"
    dependencies: ["fetch_data"]
    method: "llm/chat"
  
  # Combine everything
  - id: "final"
    dependencies: ["process", "fetch_config"]
    method: "python/execute"
```

## Parameter Substitution

### Basic Substitution

Use results from previous tasks:

```yaml
tasks:
  - id: "generate"
    method: "llm/chat"
    parameters:
      messages:
        - content: "Generate a story topic"
  
  - id: "write"
    dependencies: ["generate"]
    parameters:
      messages:
        - content: "Write a story about: ${generate.response}"
```

### Nested Field Access

Access nested fields in results:

```yaml
tasks:
  - id: "data_task"
    method: "python/execute"
    # Returns: {"stats": {"count": 42, "average": 3.14}}
  
  - id: "report"
    dependencies: ["data_task"]
    parameters:
      messages:
        - content: "Count: ${data_task.stats.count}, Avg: ${data_task.stats.average}"
```

### Multiple Substitutions

```yaml
tasks:
  - id: "task1"
    method: "llm/chat"
  
  - id: "task2"
    method: "llm/chat"
  
  - id: "combine"
    dependencies: ["task1", "task2"]
    parameters:
      messages:
        - content: |
            First result: ${task1.response}
            Second result: ${task2.response}
```

## Batch Processing

### Basic Batch Workflow

```yaml
name: "Batch Processor"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: "Summarize: ${file_content}"
```

### Advanced Batch Configuration

```yaml
name: "Advanced Batch"
type: "batch"
batch:
  directory: "data"
  pattern: "**/*.json"      # Recursive search
  max_concurrent: 10        # Process 10 files at once
  max_file_size: 1048576    # Skip files over 1MB
  output: "results"         # Save results to directory
template:
  method: "llm/chat"
  model: "llama3.2"
  temperature: 0.7
  messages:
    - role: "system"
      content: "You are a data analyst"
    - role: "user"
      content: "Analyze: ${file_content}"
```

## Conditional Execution

While Gleitzeit doesn't have built-in conditionals, you can implement them using Python tasks:

```yaml
tasks:
  - id: "check_condition"
    method: "python/execute"
    parameters:
      script: "check_condition.py"
      # Returns: {"should_continue": true/false}
  
  - id: "conditional_task"
    dependencies: ["check_condition"]
    method: "python/execute"
    parameters:
      script: "conditional_execute.py"
      args:
        condition: "${check_condition.should_continue}"
```

## Working with Different Providers

### LLM Tasks

```yaml
tasks:
  - id: "chat"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      temperature: 0.7
      max_tokens: 500
      messages:
        - role: "system"
          content: "You are helpful"
        - role: "user"
          content: "Hello"
```

### Python Execution

```yaml
tasks:
  - id: "python_task"
    method: "python/execute"
    parameters:
      script: "process.py"
      args:
        input: "data.csv"
        output: "results.json"
      timeout: 60
```

### Workflow Template Generation

```yaml
tasks:
  - id: "generate_research"
    method: "template/research"
    parameters:
      topic: "Machine Learning Trends"
      depth: "deep"
      max_steps: 5
```

This generates a complete multi-step research workflow.

### Vision Analysis

```yaml
tasks:
  - id: "analyze_image"
    method: "llm/vision"
    parameters:
      model: "llava"
      images:
        - "photo.jpg"
      messages:
        - role: "user"
          content: "What's in this image?"
```

## Input Parameters

### Workflow-level Inputs

```yaml
name: "Parameterized Workflow"
inputs:
  topic:
    type: "string"
    description: "Topic to write about"
    default: "AI"
  
tasks:
  - id: "write"
    method: "llm/chat"
    parameters:
      messages:
        - content: "Write about ${input.topic}"
```

Run with inputs:

```bash
gleitzeit run workflow.yaml --input topic="Machine Learning"
```

## Error Handling

### Task-level Error Handling

```yaml
tasks:
  - id: "risky_task"
    method: "python/execute"
    retry:
      max_attempts: 3
      delay: 5
    on_error: "continue"  # or "stop"
    parameters:
      script: "risky_operation.py"
```

### Workflow-level Settings

```yaml
name: "Robust Workflow"
settings:
  continue_on_error: true
  max_parallel_tasks: 5
  default_timeout: 30

tasks:
  # Tasks inherit settings
```

## Best Practices

1. **Use descriptive task IDs** - Makes debugging easier
2. **Set appropriate timeouts** - Prevent hanging workflows
3. **Add retry logic** - Handle transient failures
4. **Validate inputs** - Check data before processing
5. **Log important steps** - Use Python tasks for logging
6. **Test incrementally** - Build workflows step by step
7. **Use parameter substitution** - Avoid hardcoding values
8. **Document complex workflows** - Add descriptions

## Examples

### Data Pipeline

```yaml
name: "ETL Pipeline"
tasks:
  - id: "extract"
    method: "python/execute"
    parameters:
      script: "extract_from_db.py"
  
  - id: "transform"
    method: "python/execute"
    dependencies: ["extract"]
    parameters:
      script: "transform_data.py"
      args:
        data: "${extract.result}"
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["transform"]
    parameters:
      model: "llama3.2"
      messages:
        - content: "Analyze trends in: ${transform.summary}"
  
  - id: "load"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      script: "load_to_warehouse.py"
      args:
        data: "${transform.result}"
        insights: "${analyze.response}"
```

### Multi-Model Analysis

```yaml
name: "Multi-Model Analysis"
tasks:
  - id: "fast_analysis"
    method: "llm/chat"
    parameters:
      model: "phi"  # Small, fast model
      messages:
        - content: "Quick analysis of: ${input.text}"
  
  - id: "detailed_analysis"
    method: "llm/chat"
    parameters:
      model: "llama3.2"  # Larger model
      messages:
        - content: "Detailed analysis of: ${input.text}"
  
  - id: "code_review"
    method: "llm/chat"
    parameters:
      model: "codellama"  # Specialized model
      messages:
        - content: "Review code quality: ${input.text}"
  
  - id: "combine"
    method: "llm/chat"
    dependencies: ["fast_analysis", "detailed_analysis", "code_review"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "system"
          content: "You are a report generator. Create well-formatted reports."
        - role: "user"
          content: |
            Create a comprehensive analysis report combining:
            
            Quick Analysis: ${fast_analysis.response}
            
            Detailed Analysis: ${detailed_analysis.response}
            
            Code Review: ${code_review.response}
            
            Format as a professional report with sections.
```