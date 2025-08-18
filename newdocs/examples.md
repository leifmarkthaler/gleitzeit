# Example Workflows

Copy-paste ready workflows for common tasks.

## Basic Examples

### Simple Chat
```yaml
name: "Chat"
tasks:
  - id: "chat"
    method: "llm/chat"
    parameters:
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
      model: "llama3.2"
      messages:
        - role: "system"
          content: "Answer questions accurately and concisely"
        - role: "user"
          content: "${input.question}"
```

## Document Processing

### Document Summarizer
```yaml
name: "Document Summarizer"
tasks:
  - id: "read_file"
    method: "python/execute"
    parameters:
      code: |
        with open('document.txt') as f:
            return f.read()
  
  - id: "summarize"
    method: "llm/chat"
    dependencies: ["read_file"]
    parameters:
      messages:
        - role: "user"
          content: |
            Summarize this document in 3 bullet points:
            ${read_file.result}
```

### Batch PDF Processor
```yaml
name: "PDF Analyzer"
type: "batch"
batch:
  directory: "pdfs"
  pattern: "*.pdf"
  output: "analysis"
  max_concurrent: 5
template:
  method: "llm/vision"  # For PDFs with images
  model: "llava"
  messages:
    - role: "user"
      content: |
        Analyze this document:
        1. Main topic
        2. Key points (5 bullets)
        3. Action items
        
        Document: ${file_content}
```

## Data Analysis

### CSV Data Analyzer
```yaml
name: "CSV Analysis"
tasks:
  - id: "load_data"
    method: "python/execute"
    parameters:
      code: |
        import csv
        import json
        
        with open('sales.csv') as f:
            reader = csv.DictReader(f)
            data = list(reader)
        
        # Basic stats
        total_sales = sum(float(row['amount']) for row in data)
        avg_sale = total_sales / len(data)
        
        return {
            'row_count': len(data),
            'total_sales': total_sales,
            'average_sale': avg_sale,
            'sample_data': data[:5]
        }
  
  - id: "analyze"
    method: "llm/chat"
    dependencies: ["load_data"]
    parameters:
      model: "gpt-4"
      messages:
        - role: "user"
          content: |
            Analyze this sales data and provide insights:
            ${load_data.result}
            
            Include:
            - Key trends
            - Anomalies
            - Recommendations
  
  - id: "create_report"
    method: "python/execute"
    dependencies: ["analyze"]
    parameters:
      code: |
        report = """
        # Sales Analysis Report
        
        ${analyze.response}
        
        ## Raw Statistics
        - Total Sales: $${load_data.result.total_sales}
        - Average Sale: $${load_data.result.average_sale}
        - Records Analyzed: ${load_data.result.row_count}
        """
        
        with open('sales_report.md', 'w') as f:
            f.write(report)
        
        return "Report saved to sales_report.md"
```

## Content Generation

### Blog Post Generator
```yaml
name: "Blog Generator"
tasks:
  - id: "research"
    method: "llm/chat"
    parameters:
      model: "gpt-4"
      messages:
        - role: "user"
          content: "Research and list 5 key points about ${input.topic}"
  
  - id: "outline"
    method: "llm/chat"
    dependencies: ["research"]
    parameters:
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
      code: |
        import datetime
        
        filename = f"blog_{datetime.date.today()}.md"
        with open(filename, 'w') as f:
            f.write("${write.response}")
        
        return f"Blog saved to {filename}"
```

### Multi-Language Translation
```yaml
name: "Translator"
tasks:
  - id: "translate_spanish"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Translate to Spanish: ${input.text}"
  
  - id: "translate_french"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Translate to French: ${input.text}"
  
  - id: "translate_german"
    method: "llm/chat"
    parameters:
      messages:
        - role: "user"
          content: "Translate to German: ${input.text}"
  
  - id: "combine"
    method: "python/execute"
    dependencies: ["translate_spanish", "translate_french", "translate_german"]
    parameters:
      code: |
        translations = {
            "original": "${input.text}",
            "spanish": "${translate_spanish.response}",
            "french": "${translate_french.response}",
            "german": "${translate_german.response}"
        }
        
        import json
        with open('translations.json', 'w') as f:
            json.dump(translations, f, indent=2)
        
        return translations
```

## Code Analysis

### Code Reviewer
```yaml
name: "Code Review"
tasks:
  - id: "read_code"
    method: "python/execute"
    parameters:
      code: |
        import glob
        files = {}
        for path in glob.glob("src/**/*.py", recursive=True):
            with open(path) as f:
                files[path] = f.read()
        return files
  
  - id: "review"
    method: "llm/chat"
    dependencies: ["read_code"]
    parameters:
      model: "gpt-4"
      messages:
        - role: "system"
          content: "You are an expert code reviewer"
        - role: "user"
          content: |
            Review this Python code for:
            - Bugs
            - Security issues
            - Performance problems
            - Best practices
            
            Code files: ${read_code.result}
```

### Test Generator
```yaml
name: "Test Generator"
tasks:
  - id: "analyze_function"
    method: "llm/chat"
    parameters:
      model: "gpt-4"
      messages:
        - role: "user"
          content: |
            Analyze this function and identify test cases:
            
            ```python
            ${input.function_code}
            ```
  
  - id: "generate_tests"
    method: "llm/chat"
    dependencies: ["analyze_function"]
    parameters:
      messages:
        - role: "system"
          content: "You are a Python testing expert. Use pytest."
        - role: "user"
          content: |
            Generate comprehensive pytest tests based on this analysis:
            ${analyze_function.response}
            
            Include:
            - Happy path tests
            - Edge cases
            - Error cases
            - Fixtures if needed
```

## Advanced Workflows

### RAG Pipeline
```yaml
name: "RAG Q&A"
tasks:
  - id: "chunk_documents"
    method: "python/execute"
    parameters:
      code: |
        import os
        chunks = []
        for file in os.listdir("knowledge_base"):
            if file.endswith(".txt"):
                with open(f"knowledge_base/{file}") as f:
                    content = f.read()
                    # Simple chunking by paragraphs
                    chunks.extend(content.split("\n\n"))
        return chunks[:10]  # Limit for context
  
  - id: "find_relevant"
    method: "llm/chat"
    dependencies: ["chunk_documents"]
    parameters:
      messages:
        - role: "user"
          content: |
            Question: ${input.question}
            
            Which of these text chunks are relevant?
            ${chunk_documents.result}
            
            Return only the relevant chunks.
  
  - id: "answer"
    method: "llm/chat"
    dependencies: ["find_relevant"]
    parameters:
      messages:
        - role: "system"
          content: "Answer based only on the provided context"
        - role: "user"
          content: |
            Context: ${find_relevant.response}
            Question: ${input.question}
            
            Answer:
```

### Sentiment Analysis Pipeline
```yaml
name: "Sentiment Analyzer"
type: "batch"
batch:
  directory: "reviews"
  pattern: "*.txt"
template:
  method: "llm/chat"
  messages:
    - role: "user"
      content: |
        Analyze sentiment:
        
        Text: ${file_content}
        
        Return:
        - Sentiment: (positive/negative/neutral)
        - Score: (0-100)
        - Key phrases:
        - Recommendation:
```

## Running Examples

### From CLI
```bash
# Run a workflow
gleitzeit run examples/blog_generator.yaml

# With input parameters
gleitzeit run code_review.yaml --input function_code="def add(a, b): return a + b"

# Batch processing
gleitzeit run batch_analyzer.yaml --directory documents --pattern "*.pdf"
```

### From Python
```python
from gleitzeit import Client

async with Client() as client:
    # Run with inputs
    result = await client.run_workflow(
        "blog_generator.yaml",
        inputs={"topic": "AI in Healthcare"}
    )
    
    # Get specific outputs
    blog_content = result["write"]["response"]
```

## Tips

1. **Start simple** - Test with one task before chaining
2. **Use dependencies** - Control execution order
3. **Parameter substitution** - `${task_id.field}` to pass data
4. **Parallel tasks** - No dependencies = parallel execution
5. **Error handling** - Add retry configuration for reliability
6. **Model selection** - Choose appropriate models for each task