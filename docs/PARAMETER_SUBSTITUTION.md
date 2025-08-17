# Parameter Substitution

Parameter substitution allows tasks to use results from previously completed tasks, enabling complex workflow chains and data flow between steps.

## Basic Syntax

Use `${task_id.field}` to reference results from completed tasks:

```yaml
tasks:
  - id: "generate_topic"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Generate a random topic"
  
  - id: "expand_topic"
    method: "llm/chat" 
    dependencies: ["generate_topic"]
    parameters:
      messages:
        - role: "user"
          content: "Expand on this topic: ${generate_topic.response}"
```

## Available Fields

### Standard Task Fields

Every completed task provides these fields:

- `response`: Main task output/result
- `metadata`: Task execution metadata
- `duration`: Execution time in seconds
- `status`: Final task status
- `timestamp`: Completion timestamp

```yaml
parameters:
  content: "${task1.response}"           # Main result
  execution_time: ${task1.duration}      # Numeric value (no quotes)
  model_used: "${task1.metadata.model}"  # Nested field access
```

### Provider-Specific Fields

Different providers may add additional fields:

#### LLM Provider (`llm/chat`, `llm/vision`)
```yaml
# Available fields after LLM task completion
parameters:
  text: "${llm_task.response}"                    # Generated text
  model: "${llm_task.metadata.model}"            # Model used
  tokens: ${llm_task.metadata.usage.total_tokens} # Token count
  cost: ${llm_task.metadata.cost}                # Estimated cost
```

#### Python Provider (`python/execute`)
```yaml
# Available fields after Python task completion  
parameters:
  result: "${python_task.response}"              # Script output
  variables: "${python_task.metadata.variables}" # Exported variables
  exit_code: ${python_task.metadata.exit_code}   # Execution status
```

#### MCP Provider (`mcp/*`)
```yaml
# Available fields after MCP task completion
parameters:
  result: "${mcp_task.response}"              # Tool output
  tool_name: "${mcp_task.metadata.tool}"     # Tool used
  execution_time: ${mcp_task.duration}       # Timing info
```

## Advanced Usage

### Nested Field Access

Access nested data structures using dot notation:

```yaml
parameters:
  # Access nested configuration
  timeout: ${config_task.settings.execution.timeout}
  
  # Access array elements (if supported by data)
  first_result: "${batch_task.results.0.content}"
  
  # Complex nested access
  model_config: "${setup_task.llm.models.chat.parameters}"
```

### Conditional Substitution

Some advanced patterns:

```yaml
parameters:
  # Use different content based on previous task status
  content: |
    Previous task status: ${previous_task.status}
    Result: ${previous_task.response}
    Duration: ${previous_task.duration}s
```

### Multiple Substitutions

Combine multiple task results:

```yaml
parameters:
  combined_analysis: |
    Topic Analysis: ${topic_task.response}
    
    Sentiment: ${sentiment_task.response}
    
    Summary: ${summary_task.response}
    
    Confidence: ${confidence_task.metadata.score}
```

## Data Types

### String Values (with quotes)
```yaml
parameters:
  text_content: "${task1.response}"
  model_name: "${task1.metadata.model}"
```

### Numeric Values (no quotes)
```yaml
parameters:
  timeout: ${task1.duration}
  token_count: ${task1.metadata.tokens}
  score: ${task1.metadata.confidence}
```

### Boolean Values
```yaml
parameters:
  success: ${task1.metadata.success}
  should_retry: ${task1.metadata.retry_needed}
```

## Substitution Resolution

### Resolution Order

1. **Dependency Check**: Ensures referenced task completed successfully
2. **Field Validation**: Verifies requested field exists
3. **Type Conversion**: Converts data to appropriate YAML type
4. **Substitution**: Replaces placeholder with actual value

### Error Handling

If substitution fails:
- Task marked as FAILED
- Error logged with details
- Dependent tasks cancelled
- Workflow stops

```yaml
# This will fail if 'nonexistent_task' doesn't exist
parameters:
  bad_reference: "${nonexistent_task.response}"
```

### Safe Substitution

Ensure tasks exist and have required fields:

```yaml
# Good: Task clearly defined as dependency
- id: "analysis"
  method: "llm/chat"
  dependencies: ["data_prep"]  # Explicit dependency
  parameters:
    content: "${data_prep.response}"  # Safe substitution
```

## Common Patterns

### Chain of Transformations

```yaml
tasks:
  - id: "extract"
    method: "python/execute"
    parameters:
      code: "result = extract_data(input_file)"
  
  - id: "transform"
    method: "python/execute"
    dependencies: ["extract"]
    parameters:
      code: |
        raw_data = ${extract.response}
        result = transform_data(raw_data)
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["transform"]
    parameters:
      messages:
        - role: "user"
          content: "Analyze this data: ${transform.response}"
```

### Parallel Processing with Aggregation

```yaml
tasks:
  # Parallel analysis tasks
  - id: "analyze_sentiment"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Analyze sentiment: ${input.text}"
  
  - id: "analyze_topics"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Extract topics: ${input.text}"
  
  # Aggregation task
  - id: "final_report"
    method: "llm/chat"
    dependencies: ["analyze_sentiment", "analyze_topics"]
    parameters:
      messages:
        - role: "user"
          content: |
            Create a report combining:
            Sentiment: ${analyze_sentiment.response}
            Topics: ${analyze_topics.response}
```

### Dynamic Configuration

```yaml
tasks:
  - id: "configure"
    method: "python/execute"
    parameters:
      code: |
        result = {
          "model": "llama3.2:latest",
          "temperature": 0.7,
          "max_tokens": 1000
        }
  
  - id: "generate"
    method: "llm/chat"
    dependencies: ["configure"]
    parameters:
      model: "${configure.response.model}"
      temperature: ${configure.response.temperature}
      max_tokens: ${configure.response.max_tokens}
      messages:
        - role: "user"
          content: "Generate content with dynamic config"
```

## Best Practices

### Field Validation

1. **Check field existence**: Ensure referenced fields actually exist
2. **Use appropriate types**: Match data types (string vs numeric)
3. **Handle missing data**: Plan for cases where fields might be empty

### Performance

1. **Minimize deep nesting**: Complex nested access can be slow
2. **Cache common references**: Store frequently used values
3. **Use direct references**: Avoid unnecessary data transformation

### Debugging

1. **Use descriptive task IDs**: Makes substitution references clear
2. **Log substitution values**: Help debug workflow issues
3. **Test substitution patterns**: Verify before production use

### Security

1. **Validate input data**: Don't trust substituted content blindly
2. **Sanitize outputs**: Clean data before using in sensitive contexts
3. **Limit field access**: Only expose necessary fields

## Limitations

- No arithmetic operations in substitution expressions
- No conditional logic within substitutions
- Field access is read-only (no modification)
- Circular references are not allowed
- Case-sensitive field names

For complex data transformation, use Python tasks with substitution rather than trying to do everything in YAML.