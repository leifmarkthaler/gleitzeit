"""
Workflow template endpoints for example workflows
"""

from fastapi import APIRouter, Request
from typing import List, Dict, Any

router = APIRouter()

# Pre-defined workflow templates
WORKFLOW_TEMPLATES = {
    "simple_llm": {
        "id": "simple_llm",
        "name": "Simple LLM Chat",
        "description": "Basic LLM chat interaction",
        "category": "llm",
        "workflow": {
            "name": "Simple LLM Chat",
            "tasks": [
                {
                    "id": "chat1",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Hello! Can you help me?"}
                        ]
                    }
                }
            ]
        }
    },
    "multi_step_analysis": {
        "id": "multi_step_analysis",
        "name": "Multi-Step Text Analysis",
        "description": "Analyze text with multiple LLM tasks",
        "category": "llm",
        "workflow": {
            "name": "Multi-Step Text Analysis",
            "tasks": [
                {
                    "id": "summarize",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Summarize this text: ${input_text}"}
                        ]
                    }
                },
                {
                    "id": "sentiment",
                    "method": "llm/chat",
                    "depends_on": ["summarize"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Analyze the sentiment of: ${tasks.summarize.result}"}
                        ]
                    }
                },
                {
                    "id": "keywords",
                    "method": "llm/chat",
                    "depends_on": ["summarize"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Extract keywords from: ${tasks.summarize.result}"}
                        ]
                    }
                }
            ],
            "inputs": {
                "input_text": "Enter the text to analyze..."
            }
        }
    },
    "python_code_exec": {
        "id": "python_code_exec",
        "name": "Python Code Execution",
        "description": "Execute Python code and get results",
        "category": "python",
        "workflow": {
            "name": "Python Code Execution",
            "tasks": [
                {
                    "id": "exec_code",
                    "method": "python/run",
                    "parameters": {
                        "code": "import math\\nresult = math.sqrt(16)\\nprint(f'Square root of 16 is {result}')"
                    }
                }
            ]
        }
    },
    "data_processing": {
        "id": "data_processing",
        "name": "Data Processing Pipeline",
        "description": "Process data with Python and analyze with LLM",
        "category": "hybrid",
        "workflow": {
            "name": "Data Processing Pipeline",
            "tasks": [
                {
                    "id": "generate_data",
                    "method": "python/run",
                    "parameters": {
                        "code": "import json\\nimport random\\ndata = [{'value': random.randint(1, 100)} for _ in range(10)]\\nprint(json.dumps(data))"
                    }
                },
                {
                    "id": "process_data",
                    "method": "python/run",
                    "depends_on": ["generate_data"],
                    "parameters": {
                        "code": "import json\\ndata = json.loads('${tasks.generate_data.result}')\\ntotal = sum(item['value'] for item in data)\\naverage = total / len(data)\\nprint(f'Total: {total}, Average: {average}')"
                    }
                },
                {
                    "id": "analyze_results",
                    "method": "llm/chat",
                    "depends_on": ["process_data"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Provide insights about these statistics: ${tasks.process_data.result}"}
                        ]
                    }
                }
            ]
        }
    },
    "parallel_tasks": {
        "id": "parallel_tasks",
        "name": "Parallel Task Execution",
        "description": "Execute multiple tasks in parallel",
        "category": "advanced",
        "workflow": {
            "name": "Parallel Task Execution",
            "tasks": [
                {
                    "id": "task_a",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Generate a haiku about programming"}
                        ]
                    }
                },
                {
                    "id": "task_b",
                    "method": "llm/chat",
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "List 5 programming languages"}
                        ]
                    }
                },
                {
                    "id": "task_c",
                    "method": "python/run",
                    "parameters": {
                        "code": "import datetime\\nprint(f'Current time: {datetime.datetime.now()}')"
                    }
                },
                {
                    "id": "combine_results",
                    "method": "llm/chat",
                    "depends_on": ["task_a", "task_b", "task_c"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Combine these results into a summary:\\nHaiku: ${tasks.task_a.result}\\nLanguages: ${tasks.task_b.result}\\nTime: ${tasks.task_c.result}"}
                        ]
                    }
                }
            ]
        }
    },
    "web_scraping": {
        "id": "web_scraping",
        "name": "Web Scraping with Analysis",
        "description": "Fetch web content and analyze it",
        "category": "mcp",
        "workflow": {
            "name": "Web Scraping and Analysis",
            "tasks": [
                {
                    "id": "fetch_page",
                    "method": "mcp/fetch",
                    "parameters": {
                        "server": "fetch",
                        "url": "${webpage_url}"
                    }
                },
                {
                    "id": "extract_content",
                    "method": "python/run",
                    "depends_on": ["fetch_page"],
                    "parameters": {
                        "code": "from bs4 import BeautifulSoup\\nhtml = '''${tasks.fetch_page.result}'''\\nsoup = BeautifulSoup(html, 'html.parser')\\ntext = soup.get_text()[:500]\\nprint(text)"
                    }
                },
                {
                    "id": "analyze_content",
                    "method": "llm/chat",
                    "depends_on": ["extract_content"],
                    "parameters": {
                        "model": "llama3.2",
                        "messages": [
                            {"role": "user", "content": "Summarize this content: ${tasks.extract_content.result}"}
                        ]
                    }
                }
            ],
            "inputs": {
                "webpage_url": "https://example.com"
            }
        }
    }
}

@router.get("")
async def list_templates(
    request: Request,
    category: str = None
) -> Dict[str, Any]:
    """
    List all available workflow templates
    
    Args:
        category: Filter by category (llm, python, mcp, hybrid, advanced)
    
    Returns:
        List of workflow templates
    """
    templates = []
    
    for template_id, template in WORKFLOW_TEMPLATES.items():
        if category and template.get("category") != category:
            continue
        
        templates.append({
            "id": template["id"],
            "name": template["name"],
            "description": template["description"],
            "category": template["category"],
            "task_count": len(template["workflow"].get("tasks", []))
        })
    
    return {
        "templates": templates,
        "total": len(templates),
        "categories": ["llm", "python", "mcp", "hybrid", "advanced"]
    }

@router.get("/{template_id}")
async def get_template(
    request: Request,
    template_id: str
) -> Dict[str, Any]:
    """
    Get a specific workflow template
    
    Args:
        template_id: Template identifier
    
    Returns:
        Complete workflow template with definition
    """
    if template_id not in WORKFLOW_TEMPLATES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    template = WORKFLOW_TEMPLATES[template_id]
    return {
        "id": template["id"],
        "name": template["name"],
        "description": template["description"],
        "category": template["category"],
        "workflow": template["workflow"]
    }

@router.post("/{template_id}/deploy")
async def deploy_template(
    request: Request,
    template_id: str,
    inputs: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Deploy a workflow template with optional input substitution
    
    Args:
        template_id: Template identifier
        inputs: Optional input values to substitute
    
    Returns:
        Workflow submission response
    """
    if template_id not in WORKFLOW_TEMPLATES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
    
    # Get the template
    template = WORKFLOW_TEMPLATES[template_id]
    workflow = template["workflow"].copy()
    
    # Substitute inputs if provided
    if inputs:
        import json
        workflow_str = json.dumps(workflow)
        for key, value in inputs.items():
            workflow_str = workflow_str.replace(f"${{{key}}}", str(value))
        workflow = json.loads(workflow_str)
    
    # Submit the workflow
    from .workflows import submit_workflow
    return await submit_workflow(request, workflow)

@router.get("/categories")
async def get_categories(request: Request) -> Dict[str, Any]:
    """
    Get all template categories with counts
    
    Returns:
        Categories with template counts
    """
    categories = {}
    
    for template in WORKFLOW_TEMPLATES.values():
        cat = template.get("category", "other")
        if cat not in categories:
            categories[cat] = {
                "name": cat,
                "count": 0,
                "description": ""
            }
        categories[cat]["count"] += 1
    
    # Add descriptions
    category_descriptions = {
        "llm": "LLM-based workflows using Ollama models",
        "python": "Python code execution workflows",
        "mcp": "MCP tool integration workflows",
        "hybrid": "Workflows combining multiple providers",
        "advanced": "Complex workflows with advanced features"
    }
    
    for cat, info in categories.items():
        info["description"] = category_descriptions.get(cat, "Other workflows")
    
    return {
        "categories": list(categories.values()),
        "total": len(categories)
    }