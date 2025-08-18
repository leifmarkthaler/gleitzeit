# Workflow Templates

## Overview

Gleitzeit's Workflow Template system provides pre-built workflow patterns for common multi-step tasks. Templates are convenience shortcuts that generate structured workflows from simple parameters, saving users from manually writing complex YAML workflows.

## What Templates Are

**Templates are workflow generators** - they create multi-step workflows with proper dependencies, parameter substitution, and task orchestration. Instead of manually writing 5+ interconnected tasks, you can call a single template method.

## Available Templates

### template/research
Generates a 5-step research workflow:
1. **Research Planning** - Creates structured methodology
2. **Background Research** - Gathers historical context  
3. **Current Trends** - Analyzes recent developments
4. **Analysis** - Synthesizes findings and insights
5. **Final Report** - Comprehensive report with recommendations

**Parameters:**
- `topic` (required) - Research topic
- `depth` (optional) - "shallow", "medium", "deep" (default: "medium")
- `max_steps` (optional) - 1-10 steps (default: 5)

### template/code
Generates a 4-5 step code development workflow:
1. **Requirements Analysis** - Analyzes task requirements
2. **Code Generation** - Implements solution with best practices
3. **Code Testing** - Executes and validates (Python only)
4. **Code Review** - Reviews quality and optimization
5. **Documentation** - Creates usage docs and examples

**Parameters:**
- `task` (required) - Coding task description
- `language` (optional) - Programming language (default: "python")

### template/analyze
Generates a single-step content analysis workflow:
1. **Content Analysis** - Structured analysis of provided content

**Parameters:**
- `content` (required) - Content to analyze
- `question` (optional) - Specific question (default: "Provide comprehensive analysis")

### template/chat
Generates a simple conversational workflow:
1. **Chat Response** - Generates response to message

**Parameters:**
- `message` (required) - Message to respond to
- `session_id` (optional) - Session identifier

## Usage Examples

### Basic Template Usage

```yaml
name: "Research Example"
tasks:
  - id: "research_task"
    protocol: "template/v1"
    method: "template/research"
    params:
      topic: "artificial intelligence in healthcare"
      depth: "medium"
```

### Chaining Templates

```yaml
name: "Research and Implementation"
tasks:
  - id: "research"
    protocol: "template/v1"
    method: "template/research"
    params:
      topic: "microservices architecture patterns"
  
  - id: "implementation"
    protocol: "template/v1"
    method: "template/code"
    dependencies: ["research"]
    params:
      task: "Implement microservice based on research: ${research.report}"
      language: "python"
  
  - id: "analysis"
    protocol: "template/v1"
    method: "template/analyze"
    dependencies: ["research", "implementation"]
    params:
      content: "Research: ${research.report}\nCode: ${implementation.code}"
      question: "How well does the implementation follow best practices?"
```

## Benefits and Limitations

**Benefits:**
- Convenience shortcuts for complex workflows
- Standardized, tested patterns
- No manual workflow design needed

**Limitations:**
- Fixed workflow structure (no dynamic adaptation)
- Can't customize individual step prompts
- Same functionality as manual workflows, just packaged differently

Templates are essentially pre-written workflow snippets - useful for common patterns but not fundamentally different from manual workflows.