# AI-Assisted Development Enhancement for Gleitzeit

## Executive Summary

This document outlines enhancements to transform Gleitzeit from a workflow orchestration engine into a comprehensive AI-assisted development platform, combining its robust execution capabilities with intelligent knowledge management and code-aware features.

## Core Additions

### 1. Knowledge Management System

#### Architecture
```python
# New module: gleitzeit/knowledge/
class KnowledgeHub:
    """
    Persistent knowledge management across workflow executions.
    Integrates with existing persistence layer.
    """
    
    def __init__(self, persistence: UnifiedPersistenceAdapter, vector_db: VectorDB):
        self.persistence = persistence
        self.vector_db = vector_db  # ChromaDB, Qdrant, or FAISS
        self.embeddings = EmbeddingProvider()  # Ollama or OpenAI
    
    async def index_codebase(self, path: str, project_id: str):
        """Index local code repository for context retrieval"""
        files = await self._scan_code_files(path)
        for file in files:
            content = await self._read_file(file)
            chunks = self._chunk_code(content, language=file.suffix)
            embeddings = await self.embeddings.encode(chunks)
            await self.vector_db.store(
                documents=chunks,
                embeddings=embeddings,
                metadata={"project": project_id, "file": file, "type": "code"}
            )
    
    async def add_documentation(self, url: str, project_id: str):
        """Crawl and index documentation"""
        content = await self._crawl_url(url)
        chunks = self._chunk_text(content)
        embeddings = await self.embeddings.encode(chunks)
        await self.vector_db.store(
            documents=chunks,
            embeddings=embeddings,
            metadata={"project": project_id, "source": url, "type": "docs"}
        )
    
    async def semantic_search(self, query: str, project_id: str, k: int = 5):
        """Find relevant context using semantic similarity"""
        query_embedding = await self.embeddings.encode([query])
        results = await self.vector_db.search(
            embedding=query_embedding[0],
            filter={"project": project_id},
            k=k
        )
        return results
    
    async def get_context_for_task(self, task: Task, max_tokens: int = 4000):
        """Automatically retrieve relevant context for a task"""
        # Extract search query from task parameters
        query = self._extract_query_from_task(task)
        
        # Search for relevant context
        results = await self.semantic_search(query, task.project_id)
        
        # Optimize context to fit within token limits
        context = self._optimize_context(results, max_tokens)
        return context
```

#### Integration with Existing Providers

```python
# Enhanced OllamaProvider
class EnhancedOllamaProvider(OllamaProvider):
    def __init__(self, *args, knowledge_hub: Optional[KnowledgeHub] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.knowledge_hub = knowledge_hub
    
    async def _chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        # Auto-inject context if knowledge hub is available
        if self.knowledge_hub and params.get("use_context", True):
            context = await self.knowledge_hub.get_context_for_task(
                self.current_task,
                max_tokens=params.get("context_tokens", 4000)
            )
            
            # Inject context as system message
            if context:
                params["messages"].insert(0, {
                    "role": "system",
                    "content": f"Relevant context:\n{context}"
                })
        
        return await super()._chat(params)
```

### 2. Session Management

#### Conversation Memory
```python
class ConversationSession:
    """Maintain context across multiple interactions"""
    
    def __init__(self, session_id: str, client: GleitzeitClient):
        self.session_id = session_id
        self.client = client
        self.history: List[Dict[str, str]] = []
        self.context: Dict[str, Any] = {}
        self.knowledge_refs: List[str] = []
    
    async def chat(self, message: str, save_context: bool = True) -> str:
        """Chat with memory of previous interactions"""
        self.history.append({"role": "user", "content": message})
        
        # Include conversation history
        response = await self.client.execute_task(
            protocol="llm/v1",
            method="llm/chat",
            params={
                "messages": self.history,
                "session_id": self.session_id,
                "use_context": True
            }
        )
        
        self.history.append({"role": "assistant", "content": response.result})
        
        # Save to persistence if requested
        if save_context:
            await self._save_session()
        
        return response.result
    
    async def add_knowledge(self, content: str, metadata: Dict[str, Any]):
        """Add knowledge to session context"""
        ref_id = await self.client.knowledge_hub.store(
            content=content,
            metadata={**metadata, "session_id": self.session_id}
        )
        self.knowledge_refs.append(ref_id)
    
    async def recall(self, query: str) -> List[str]:
        """Search session-specific knowledge"""
        return await self.client.knowledge_hub.search(
            query=query,
            filter={"session_id": self.session_id}
        )
```

### 3. Code-Aware Features

#### Code Analysis Provider
```python
# New provider: gleitzeit/providers/code_provider.py
class CodeProvider(ProtocolProvider):
    """Provider for code analysis and manipulation"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(
            provider_id="code-provider",
            protocol_id="code/v1",
            name="Code Analysis Provider",
            description="Analyze and manipulate code"
        )
        self.parsers = {
            ".py": PythonParser(),
            ".js": JavaScriptParser(),
            ".ts": TypeScriptParser(),
            # Add more language parsers
        }
    
    def get_supported_methods(self) -> List[str]:
        return [
            "code/analyze",
            "code/find_definitions",
            "code/extract_dependencies",
            "code/suggest_refactoring",
            "code/generate_tests",
            "code/document"
        ]
    
    async def analyze_repository(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze repository structure and complexity"""
        path = params["path"]
        
        analysis = {
            "structure": await self._analyze_structure(path),
            "dependencies": await self._analyze_dependencies(path),
            "complexity": await self._calculate_complexity(path),
            "test_coverage": await self._analyze_test_coverage(path),
            "suggestions": []
        }
        
        # Use LLM to generate insights
        if params.get("ai_insights", True):
            insights = await self._generate_ai_insights(analysis)
            analysis["suggestions"] = insights
        
        return analysis
    
    async def find_definitions(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Find class/function definitions"""
        symbol = params["symbol"]
        path = params["path"]
        
        definitions = []
        for file in self._get_files(path):
            parser = self._get_parser(file)
            if parser:
                defs = parser.find_symbol(file, symbol)
                definitions.extend(defs)
        
        return {"symbol": symbol, "definitions": definitions}
    
    async def suggest_refactoring(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """AI-powered refactoring suggestions"""
        code = params["code"]
        language = params.get("language", "python")
        context = params.get("context", {})
        
        # Analyze code structure
        analysis = self._analyze_code(code, language)
        
        # Generate refactoring suggestions using LLM
        suggestions = await self._llm_refactor(
            code=code,
            analysis=analysis,
            context=context,
            guidelines=params.get("guidelines", [])
        )
        
        return {
            "original": code,
            "suggestions": suggestions,
            "analysis": analysis
        }
```

### 4. Workflow Enhancements

#### Knowledge-Aware Workflows
```yaml
# Example workflow with knowledge management
name: "Refactor Authentication Module"
project_id: "my-app"
session: "refactoring-session-1"

tasks:
  - id: "index_codebase"
    method: "knowledge/index"
    parameters:
      path: "./src"
      project_id: "${project_id}"
      
  - id: "analyze_current"
    method: "code/analyze"
    dependencies: ["index_codebase"]
    parameters:
      path: "./src/auth"
      ai_insights: true
      
  - id: "find_issues"
    method: "llm/chat"
    dependencies: ["analyze_current"]
    parameters:
      use_context: true  # Auto-injects relevant code context
      messages:
        - role: "user"
          content: |
            Based on the analysis: ${analyze_current.result}
            What are the main issues with the current authentication implementation?
            
  - id: "generate_refactoring_plan"
    method: "llm/chat"
    dependencies: ["find_issues"]
    parameters:
      use_context: true
      save_to_knowledge: true  # Save response to knowledge base
      messages:
        - role: "user"
          content: "Create a detailed refactoring plan to address these issues"
          
  - id: "implement_changes"
    method: "code/refactor"
    dependencies: ["generate_refactoring_plan"]
    parameters:
      files: ["./src/auth/*.py"]
      plan: "${generate_refactoring_plan.response}"
      preview: true  # Show changes before applying
```

### 5. Context Management

#### Smart Context Optimizer
```python
class ContextOptimizer:
    """Optimize context for LLM token limits"""
    
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer
    
    def prioritize_context(
        self,
        available_context: List[Dict[str, Any]],
        token_limit: int,
        task_description: str
    ) -> str:
        """Select most relevant context within token budget"""
        
        # Score each context piece by relevance
        scored_context = []
        for ctx in available_context:
            score = self._calculate_relevance(ctx, task_description)
            tokens = self.tokenizer.count_tokens(ctx["content"])
            scored_context.append({
                **ctx,
                "score": score,
                "tokens": tokens
            })
        
        # Sort by relevance score
        scored_context.sort(key=lambda x: x["score"], reverse=True)
        
        # Select context within token budget
        selected = []
        total_tokens = 0
        for ctx in scored_context:
            if total_tokens + ctx["tokens"] <= token_limit:
                selected.append(ctx["content"])
                total_tokens += ctx["tokens"]
        
        return "\n\n".join(selected)
    
    def chunk_code_intelligently(self, code: str, language: str) -> List[str]:
        """Chunk code while preserving structure"""
        parser = self._get_parser(language)
        ast = parser.parse(code)
        
        chunks = []
        for node in ast.top_level_nodes:
            chunk = {
                "type": node.type,  # class, function, etc.
                "name": node.name,
                "content": node.source,
                "dependencies": node.dependencies
            }
            chunks.append(chunk)
        
        return chunks
```

### 6. Interactive Mode

#### REPL-Style Workflow Execution
```python
class InteractiveWorkflow:
    """Interactive workflow execution with breakpoints"""
    
    async def execute_with_breakpoints(
        self,
        workflow: Workflow,
        client: GleitzeitClient
    ):
        """Execute workflow with interactive breakpoints"""
        
        for task in workflow.tasks:
            if task.params.get("breakpoint", False):
                # Pause for user input
                print(f"\n🔴 Breakpoint at task: {task.id}")
                print(f"Current context: {task.context}")
                
                while True:
                    user_input = input(">> ")
                    if user_input == "continue":
                        break
                    elif user_input.startswith("modify"):
                        # Allow parameter modification
                        task.params = self._modify_params(task.params)
                    elif user_input.startswith("inspect"):
                        # Inspect current state
                        self._inspect_state(workflow, task)
                    elif user_input == "abort":
                        return
            
            # Execute task
            result = await client.execute_task(task)
            
            if task.params.get("confirm_result", False):
                # Confirm before proceeding
                print(f"Result: {result}")
                if input("Proceed? (y/n): ") != "y":
                    return
```

## Implementation Roadmap

### Phase 1: Foundation (Weeks 1-4)
- [ ] Vector database integration (ChromaDB/Qdrant)
- [ ] Basic knowledge storage and retrieval
- [ ] Session management system
- [ ] Context injection in OllamaProvider

### Phase 2: Code Intelligence (Weeks 5-8)
- [ ] Code analysis provider
- [ ] Repository indexing
- [ ] Multi-file refactoring support
- [ ] Test generation capabilities

### Phase 3: Developer Experience (Weeks 9-12)
- [ ] Web UI for knowledge exploration
- [ ] VSCode extension
- [ ] Interactive workflow mode
- [ ] Git integration

## Quick Start Implementation

### Minimal Knowledge Store (Can implement today)
```python
# Add to gleitzeit/knowledge/__init__.py
from typing import Dict, List, Any
import json
from pathlib import Path

class SimpleKnowledgeStore:
    """Minimal knowledge store using existing persistence"""
    
    def __init__(self, persistence):
        self.persistence = persistence
        self.domain = "knowledge"
    
    async def store(self, key: str, content: str, metadata: Dict[str, Any] = None):
        """Store knowledge item"""
        await self.persistence.save(
            domain=self.domain,
            key=key,
            value={
                "content": content,
                "metadata": metadata or {},
                "timestamp": datetime.now().isoformat()
            }
        )
    
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Simple keyword search (upgrade to semantic later)"""
        all_items = await self.persistence.list_keys(self.domain)
        results = []
        
        for key in all_items:
            item = await self.persistence.get(self.domain, key)
            if query.lower() in item["content"].lower():
                results.append(item)
                if len(results) >= limit:
                    break
        
        return results
```

### Enhanced Client with Sessions
```python
# Add to client_v2.py
class GleitzeitClient:
    # ... existing code ...
    
    async def create_session(self, session_id: str) -> ConversationSession:
        """Create a new conversation session"""
        return ConversationSession(session_id, self)
    
    async def resume_session(self, session_id: str) -> ConversationSession:
        """Resume an existing session"""
        session = ConversationSession(session_id, self)
        await session.load_history()
        return session
```

## Configuration

### New Configuration Options
```yaml
# ~/.gleitzeit/config.yaml
knowledge:
  enabled: true
  vector_db: "chromadb"  # or "qdrant", "faiss"
  embedding_model: "nomic-embed-text"  # Ollama embedding model
  max_context_tokens: 4000
  auto_index_paths:
    - "./src"
    - "./docs"
    
code_analysis:
  enabled: true
  languages: ["python", "javascript", "typescript"]
  complexity_threshold: 10
  
ai_features:
  auto_context: true
  session_persistence: true
  interactive_mode: false
```

## Benefits

1. **Persistent Knowledge**: Never lose context between sessions
2. **Smarter LLM Calls**: Automatic context injection
3. **Code Understanding**: Deep analysis of codebases
4. **Developer Productivity**: AI-assisted refactoring and documentation
5. **Maintains Simplicity**: Builds on existing architecture

## Conclusion

These enhancements would transform Gleitzeit into a comprehensive AI-assisted development platform while maintaining its core strengths of reliable workflow orchestration and clean architecture. The phased approach allows for incremental implementation without disrupting existing functionality.