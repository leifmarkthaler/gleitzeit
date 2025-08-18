# 5-Minute Tutorial

Let's build a real workflow that does something useful - analyze a document and create a summary report.

## Step 1: Install and Start

```bash
# Install Gleitzeit
pip install gleitzeit

# Start Ollama (if not running)
ollama serve

# Pull a model (one-time)
ollama pull llama3.2
```

## Step 2: Your First Workflow

Create `document_analyzer.yaml`:

```yaml
name: "Document Analyzer"
tasks:
  - id: "analyze"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "system"
          content: "You are a document analyst. Be concise."
        - role: "user"
          content: |
            Analyze this text and provide:
            1. Main topic (1 sentence)
            2. Key points (3 bullets)
            3. Sentiment (positive/negative/neutral)
            
            Text: The new product launch exceeded expectations. 
            Sales were up 40% in Q1. Customer feedback has been 
            overwhelmingly positive, with a 4.8 star rating.
```

Run it:
```bash
gleitzeit run document_analyzer.yaml
```

## Step 3: Chain Tasks Together

Update your workflow to create a report:

```yaml
name: "Document Analyzer"
tasks:
  - id: "analyze"
    method: "llm/chat"
    parameters:
      model: "llama3.2"
      messages:
        - role: "user"
          content: "Analyze this quarterly report..."

  - id: "create_report"
    method: "llm/chat"
    dependencies: ["analyze"]
    parameters:
      model: "llama3.2"
      messages:
        - role: "system"
          content: "Create an executive summary based on the analysis"
        - role: "user"
          content: "Based on this analysis, write a 3-paragraph executive summary: ${analyze.response}"

  - id: "save_report"
    method: "python/execute"
    dependencies: ["create_report"]
    parameters:
      code: |
        report = '''${create_report.response}'''
        with open('executive_summary.txt', 'w') as f:
            f.write(report)
        print("Report saved to executive_summary.txt")
        return "Report saved successfully"
```

## Step 4: Process Multiple Files

Create `batch_analyzer.yaml`:

```yaml
name: "Batch Document Processor"
type: "batch"
batch:
  directory: "documents"
  pattern: "*.txt"
  output: "summaries"
template:
  method: "llm/chat"
  model: "llama3.2"
  messages:
    - role: "user"
      content: |
        Summarize this document in 3 sentences:
        ${file_content}
```

Run it:
```bash
gleitzeit run batch_analyzer.yaml
```

## Step 5: Use from Python

Create `analyze.py`:

```python
import asyncio
from gleitzeit import Client

async def analyze_documents():
    async with Client() as client:
        # Analyze a single document
        analysis = await client.chat(
            "Analyze this text for sentiment: Customer service was terrible!",
            model="llama3.2"
        )
        print(f"Sentiment: {analysis}")
        
        # Process multiple files
        results = await client.batch_process(
            directory="reports",
            pattern="*.txt",
            prompt="Summarize in 50 words",
            max_concurrent=5
        )
        
        for file, summary in results.items():
            print(f"{file}: {summary[:100]}...")

asyncio.run(analyze_documents())
```

## What You Learned

✅ Create and run workflows with YAML  
✅ Chain tasks with dependencies  
✅ Use results from one task in another with `${task_id.field}`  
✅ Process multiple files in batch  
✅ Mix LLM calls with Python code  
✅ Use Gleitzeit from Python scripts  

## Try These Next

### Add Error Handling
```yaml
tasks:
  - id: "process"
    method: "llm/chat"
    retry:
      max_attempts: 3
      delay: 2
    parameters:
      timeout: 30
      messages:
        - content: "Process this data..."
```

### Use Different Models
```yaml
parameters:
  model: "gpt-4"  # OpenAI (set OPENAI_API_KEY)
  # model: "claude-3"  # Anthropic (set ANTHROPIC_API_KEY)
  # model: "mistral"  # Local Ollama
```

### Parallel Processing
```yaml
tasks:
  - id: "task1"
    method: "llm/chat"
    # No dependencies - runs immediately
    
  - id: "task2"
    method: "llm/chat"
    # No dependencies - runs in parallel with task1
    
  - id: "combine"
    method: "python/execute"
    dependencies: ["task1", "task2"]  # Waits for both
```

## Next Steps

- [Example Workflows](examples.md) - Ready-to-use workflows
- [Python API Guide](python.md) - Full API reference
- [Advanced Features](advanced.md) - Parallel execution, retries, persistence