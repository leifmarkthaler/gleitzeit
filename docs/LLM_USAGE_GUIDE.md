# LLM Usage Guide

## Overview

This guide covers how to use Large Language Models (LLMs) in Gleitzeit workflows through the Ollama provider. Learn how to create LLM tasks, build complex workflows, and process documents with AI.

## Prerequisites

### 1. Install and Start Ollama
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
ollama serve
```

### 2. Pull Models
```bash
# Text generation models
ollama pull llama3.2:latest
ollama pull mistral:latest
ollama pull codellama:latest

# Vision models
ollama pull llava:latest
```

## Quick Start

### Simple LLM Task (CLI)
```bash
# Generate text
gleitzeit task submit llm/chat \
  --model "llama3.2:latest" \
  --messages '[{"role":"user","content":"Write a haiku about coding"}]'
```

### Simple LLM Workflow (YAML)
```yaml
# hello_llm.yaml
name: "Hello LLM"
tasks:
  - id: "generate"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Say hello in 5 different languages"
```

Run it:
```bash
gleitzeit workflow submit hello_llm.yaml
```

## Basic LLM Tasks

### Text Generation

#### Simple Prompt
```yaml
tasks:
  - id: "simple_generation"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Explain quantum computing in simple terms"
```

#### With System Prompt
```yaml
tasks:
  - id: "with_system"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "system"
          content: "You are a helpful assistant that explains things simply"
        - role: "user"
          content: "What is machine learning?"
```

#### Multi-turn Conversation
```yaml
tasks:
  - id: "conversation"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "What is Python?"
        - role: "assistant"
          content: "Python is a high-level programming language..."
        - role: "user"
          content: "Show me a simple example"
```

### File Processing

#### Process Text File
```yaml
tasks:
  - id: "analyze_file"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "document.txt"  # File content is automatically injected
      messages:
        - role: "user"
          content: "Summarize this document in 3 bullet points"
```

#### Process Code File
```yaml
tasks:
  - id: "review_code"
    method: "llm/chat"
    parameters:
      model: "codellama:latest"
      file_path: "main.py"
      messages:
        - role: "user"
          content: "Review this code for bugs and suggest improvements"
```

## Vision Tasks (Image Analysis)

### Basic Image Analysis
```yaml
tasks:
  - id: "describe_image"
    method: "llm/vision"
    parameters:
      model: "llava:latest"
      image_path: "photo.jpg"
      messages:
        - role: "user"
          content: "Describe what you see in this image"
```

### Detailed Image Analysis
```yaml
tasks:
  - id: "analyze_diagram"
    method: "llm/vision"
    parameters:
      model: "llava:latest"
      image_path: "architecture_diagram.png"
      messages:
        - role: "user"
          content: |
            Analyze this architecture diagram and:
            1. Identify all components
            2. Explain the data flow
            3. Suggest potential improvements
```

## Chained Workflows

### Sequential Processing
```yaml
name: "Content Pipeline"
tasks:
  - id: "generate_outline"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Create an outline for a blog post about AI ethics"
  
  - id: "expand_outline"
    method: "llm/chat"
    dependencies: ["generate_outline"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Expand this outline into a full blog post:
            ${generate_outline.response}
  
  - id: "create_summary"
    method: "llm/chat"
    dependencies: ["expand_outline"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Create a 2-sentence summary of this blog post:
            ${expand_outline.response}
```

### Parallel Analysis
```yaml
name: "Document Analysis"
tasks:
  # These run in parallel
  - id: "sentiment"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "review.txt"
      messages:
        - role: "user"
          content: "Analyze the sentiment (positive/negative/neutral)"
  
  - id: "key_points"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "review.txt"
      messages:
        - role: "user"
          content: "Extract 3 key points"
  
  - id: "topics"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "review.txt"
      messages:
        - role: "user"
          content: "Identify the main topics discussed"
  
  # This waits for all above tasks
  - id: "summary"
    method: "llm/chat"
    dependencies: ["sentiment", "key_points", "topics"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Create a comprehensive analysis based on:
            - Sentiment: ${sentiment.response}
            - Key Points: ${key_points.response}
            - Topics: ${topics.response}
```

## Advanced Parameters

### Temperature Control
```yaml
parameters:
  model: "llama3.2:latest"
  temperature: 0.7  # 0.0 = deterministic, 2.0 = very creative
  messages:
    - role: "user"
      content: "Write a creative story"
```

### Token Limits
```yaml
parameters:
  model: "llama3.2:latest"
  max_tokens: 500  # Limit response length
  messages:
    - role: "user"
      content: "Explain the universe"
```

### All Available Parameters
```yaml
parameters:
  model: "llama3.2:latest"
  messages: [...]
  temperature: 0.8      # Creativity (0.0-2.0)
  max_tokens: 1000     # Max response length
  top_p: 0.9          # Nucleus sampling
  top_k: 40           # Top-k sampling
  repeat_penalty: 1.1  # Reduce repetition
  seed: 42            # For reproducibility
  num_ctx: 4096       # Context window size
```

## Batch Processing

### Batch Text Files
```yaml
name: "Batch Document Analysis"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
template:
  method: "llm/chat"
  model: "llama3.2:latest"
  messages:
    - role: "user"
      content: "Summarize this document"
```

### Batch Images
```yaml
name: "Batch Image Description"
type: "batch"
batch:
  directory: "images"
  pattern: "*.jpg"
template:
  method: "llm/vision"
  model: "llava:latest"
  messages:
    - role: "user"
      content: "Describe this image"
```

### CLI Batch Processing
```bash
# Process all text files
gleitzeit batch documents --pattern "*.txt" \
  --model "llama3.2:latest" \
  --prompt "Summarize in 100 words"

# Process all images
gleitzeit batch images --pattern "*.png" \
  --model "llava:latest" \
  --prompt "What objects are in this image?" \
  --vision
```

## Real-World Examples

### Code Review Workflow
```yaml
name: "Code Review Pipeline"
tasks:
  - id: "analyze_code"
    method: "llm/chat"
    parameters:
      model: "codellama:latest"
      file_path: "src/main.py"
      messages:
        - role: "system"
          content: "You are an expert code reviewer"
        - role: "user"
          content: "Review this code for bugs, performance issues, and best practices"
  
  - id: "security_check"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "src/main.py"
      messages:
        - role: "user"
          content: "Check this code for security vulnerabilities"
  
  - id: "suggest_tests"
    method: "llm/chat"
    dependencies: ["analyze_code"]
    parameters:
      model: "codellama:latest"
      messages:
        - role: "user"
          content: |
            Based on this code review: ${analyze_code.response}
            
            Write comprehensive unit tests for the identified issues
```

### Content Generation Pipeline
```yaml
name: "Blog Post Generator"
tasks:
  - id: "research"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Research key points about sustainable technology"
  
  - id: "outline"
    method: "llm/chat"
    dependencies: ["research"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Create a blog post outline based on:
            ${research.response}
  
  - id: "write_intro"
    method: "llm/chat"
    dependencies: ["outline"]
    parameters:
      model: "llama3.2:latest"
      temperature: 0.7
      messages:
        - role: "user"
          content: |
            Write an engaging introduction for this outline:
            ${outline.response}
  
  - id: "write_body"
    method: "llm/chat"
    dependencies: ["outline"]
    parameters:
      model: "llama3.2:latest"
      temperature: 0.7
      max_tokens: 1500
      messages:
        - role: "user"
          content: |
            Write the main body for this outline:
            ${outline.response}
  
  - id: "write_conclusion"
    method: "llm/chat"
    dependencies: ["write_body"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Write a conclusion that summarizes these key points:
            ${write_body.response}
```

### Data Analysis Workflow
```yaml
name: "CSV Data Analysis"
tasks:
  - id: "analyze_data"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      file_path: "sales_data.csv"
      messages:
        - role: "user"
          content: |
            Analyze this CSV data and provide:
            1. Key statistics
            2. Trends and patterns
            3. Anomalies or outliers
  
  - id: "create_insights"
    method: "llm/chat"
    dependencies: ["analyze_data"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Based on this analysis: ${analyze_data.response}
            
            Provide 5 actionable business insights
  
  - id: "generate_report"
    method: "llm/chat"
    dependencies: ["create_insights"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: |
            Create an executive summary report including:
            - Analysis: ${analyze_data.response}
            - Insights: ${create_insights.response}
```

## Monitoring and Results

### Check Status
```bash
# Task status
gleitzeit task status TASK_ID

# Workflow status
gleitzeit workflow status WORKFLOW_ID

# System overview
gleitzeit system status
```

### View Results
```bash
# Get task result
gleitzeit task result TASK_ID

# Export workflow results
gleitzeit workflow export WORKFLOW_ID --output results.json
```

## Error Handling

### Retry Configuration
```yaml
tasks:
  - id: "with_retry"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 5
    parameters:
      model: "llama3.2:latest"
      timeout: 60
      messages:
        - role: "user"
          content: "Process this request"
```

### Timeout Settings
```yaml
tasks:
  - id: "long_task"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      timeout: 300  # 5 minutes for complex tasks
      messages:
        - role: "user"
          content: "Write a comprehensive analysis"
```

## Best Practices

### 1. Model Selection
- **llama3.2:latest** - General purpose, balanced
- **mistral:latest** - Fast, good for analysis
- **codellama:latest** - Code generation and review
- **llava:latest** - Image understanding

### 2. Temperature Guidelines
- **0.0-0.3** - Factual, consistent (analysis, extraction)
- **0.4-0.7** - Balanced (general tasks)
- **0.8-1.5** - Creative (story writing, brainstorming)

### 3. Prompt Engineering
```yaml
# Good prompt - specific and clear
messages:
  - role: "system"
    content: "You are a technical writer creating documentation"
  - role: "user"
    content: |
      Write API documentation for a user authentication endpoint.
      Include: method, parameters, responses, and examples.

# Poor prompt - vague
messages:
  - role: "user"
    content: "Write about API"
```

### 4. Resource Management
```yaml
# For large files, use smaller models
parameters:
  model: "llama3.2:3b"  # Smaller variant
  file_path: "large_document.txt"
  max_tokens: 500  # Limit output
```

### 5. Workflow Optimization
```yaml
# Run independent tasks in parallel
tasks:
  - id: "task1"
    method: "llm/chat"
    # No dependencies - runs immediately
    
  - id: "task2"
    method: "llm/chat"
    # No dependencies - runs in parallel with task1
    
  - id: "combine"
    dependencies: ["task1", "task2"]
    # Waits for both to complete
```

## Troubleshooting

### Common Issues

1. **"Ollama not reachable"**
   ```bash
   # Start Ollama
   ollama serve
   ```

2. **"Model not found"**
   ```bash
   # Pull the model
   ollama pull model_name
   ```

3. **Timeout errors**
   - Increase timeout in parameters
   - Use smaller model
   - Reduce prompt complexity

4. **Empty responses**
   - Check model compatibility
   - Verify message format
   - Review system logs

## Complete Example: Research Assistant

```yaml
name: "Research Assistant"
description: "Automated research and report generation"

tasks:
  # Step 1: Generate research questions
  - id: "generate_questions"
    method: "llm/chat"
    parameters:
      model: "llama3.2:latest"
      temperature: 0.8
      messages:
        - role: "user"
          content: "Generate 5 research questions about renewable energy"
  
  # Step 2: Research each topic (parallel)
  - id: "research_solar"
    method: "llm/chat"
    dependencies: ["generate_questions"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Research current state of solar energy technology"
  
  - id: "research_wind"
    method: "llm/chat"
    dependencies: ["generate_questions"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Research current state of wind energy technology"
  
  - id: "research_hydro"
    method: "llm/chat"
    dependencies: ["generate_questions"]
    parameters:
      model: "llama3.2:latest"
      messages:
        - role: "user"
          content: "Research current state of hydroelectric technology"
  
  # Step 3: Synthesize findings
  - id: "synthesize"
    method: "llm/chat"
    dependencies: ["research_solar", "research_wind", "research_hydro"]
    parameters:
      model: "llama3.2:latest"
      temperature: 0.5
      messages:
        - role: "user"
          content: |
            Synthesize these research findings into a cohesive analysis:
            
            Solar: ${research_solar.response}
            Wind: ${research_wind.response}
            Hydro: ${research_hydro.response}
            
            Focus on comparing efficiency, cost, and environmental impact.
  
  # Step 4: Generate final report
  - id: "final_report"
    method: "llm/chat"
    dependencies: ["synthesize"]
    parameters:
      model: "llama3.2:latest"
      temperature: 0.3
      max_tokens: 2000
      messages:
        - role: "system"
          content: "You are a professional technical writer"
        - role: "user"
          content: |
            Create a professional research report based on:
            
            Questions: ${generate_questions.response}
            Analysis: ${synthesize.response}
            
            Include:
            1. Executive Summary
            2. Key Findings
            3. Comparative Analysis
            4. Recommendations
            5. Conclusion
```

Run and get results:
```bash
# Submit workflow
gleitzeit workflow submit research_assistant.yaml

# Monitor progress
gleitzeit workflow status WORKFLOW_ID

# Export final report
gleitzeit workflow export WORKFLOW_ID --output research_report.json
```