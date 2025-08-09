#!/usr/bin/env python3
"""
LLM Orchestration Examples

Core examples showing Gleitzeit's primary strength: orchestrating LLM tasks
across multiple endpoints with intelligent load balancing.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy


# ============================================
# Example 1: Multi-Model Document Analysis
# ============================================

async def document_analysis_pipeline():
    """
    Analyze a document using multiple specialized models
    """
    
    # Configure cluster with multiple endpoints
    cluster = GleitzeitCluster(
        ollama_endpoints=[
            EndpointConfig("http://gpu-server-1:11434", priority=1, gpu=True),
            EndpointConfig("http://gpu-server-2:11434", priority=2, gpu=True),
            EndpointConfig("http://cpu-server:11434", priority=3, gpu=False),
        ],
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
    )
    
    await cluster.start()
    
    # Create workflow
    workflow = cluster.create_workflow("Document Analysis")
    
    document = """
    Quarterly Financial Report - Q3 2024
    Revenue increased by 15% year-over-year...
    New product launches in Asian markets...
    R&D investments doubled...
    """
    
    # Step 1: Extract key information using a fast model
    extraction = workflow.add_text_task(
        name="Extract Key Facts",
        prompt=f"Extract key facts and figures from:\n{document}",
        model="llama3",  # Fast 8B model
        temperature=0.1  # Low temperature for factual extraction
    )
    
    # Step 2: Financial analysis using specialized model
    financial = workflow.add_text_task(
        name="Financial Analysis",
        prompt="Analyze the financial implications: {{Extract Key Facts.result}}",
        model="mixtral",  # Good at quantitative analysis
        dependencies=["Extract Key Facts"]
    )
    
    # Step 3: Strategic insights using larger model
    strategic = workflow.add_text_task(
        name="Strategic Analysis",
        prompt="Provide strategic business insights: {{Extract Key Facts.result}}",
        model="llama3:70b",  # Larger model for complex reasoning
        dependencies=["Extract Key Facts"]
    )
    
    # Step 4: Risk assessment
    risk = workflow.add_text_task(
        name="Risk Assessment",
        prompt="Identify risks and opportunities: {{Extract Key Facts.result}}",
        model="codellama",  # Can analyze technical/operational risks
        dependencies=["Extract Key Facts"]
    )
    
    # Step 5: Executive summary combining all analyses
    summary = workflow.add_text_task(
        name="Executive Summary",
        prompt="""
        Create an executive summary based on:
        Financial Analysis: {{Financial Analysis.result}}
        Strategic Insights: {{Strategic Analysis.result}}
        Risk Assessment: {{Risk Assessment.result}}
        """,
        model="llama3:70b",
        temperature=0.7,
        dependencies=["Financial Analysis", "Strategic Analysis", "Risk Assessment"]
    )
    
    # Execute workflow
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📊 Document Analysis Complete")
    print(f"Executive Summary:\n{result.results['Executive Summary']}")
    
    await cluster.stop()


# ============================================
# Example 2: Multi-Language Translation Pipeline
# ============================================

async def translation_pipeline():
    """
    Translate content through multiple languages with quality checks
    """
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Translation Pipeline")
    
    original_text = "Artificial intelligence is transforming how we work and live."
    
    # Translate to multiple languages in parallel
    languages = ["Spanish", "French", "German", "Japanese", "Chinese"]
    
    translation_tasks = []
    for lang in languages:
        task = workflow.add_text_task(
            name=f"Translate to {lang}",
            prompt=f"Translate to {lang}: '{original_text}'. Provide only the translation.",
            model="llama3",
            temperature=0.3
        )
        translation_tasks.append(task.name)
    
    # Back-translate each to verify quality
    for lang in languages:
        workflow.add_text_task(
            name=f"Verify {lang}",
            prompt=f"Translate this {lang} text back to English: {{{{Translate to {lang}.result}}}}",
            model="llama3",
            dependencies=[f"Translate to {lang}"]
        )
    
    # Quality assessment
    workflow.add_text_task(
        name="Translation Quality Report",
        prompt=f"""
        Compare the original text with back-translations and assess quality:
        Original: {original_text}
        """ + "\n".join([f"{lang} back-translation: {{{{Verify {lang}.result}}}}" for lang in languages]),
        model="mixtral",
        dependencies=[f"Verify {lang}" for lang in languages]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🌍 Translation Pipeline Complete")
    for lang in languages:
        print(f"{lang}: {result.results[f'Translate to {lang}']}")
    
    await cluster.stop()


# ============================================
# Example 3: Code Review and Documentation
# ============================================

async def code_review_pipeline():
    """
    Automated code review with multiple specialized models
    """
    
    cluster = GleitzeitCluster(
        ollama_strategy=LoadBalancingStrategy.ROUND_ROBIN
    )
    await cluster.start()
    
    workflow = cluster.create_workflow("Code Review")
    
    code_snippet = '''
    def calculate_fibonacci(n):
        if n <= 0:
            return []
        elif n == 1:
            return [0]
        elif n == 2:
            return [0, 1]
        else:
            fib = [0, 1]
            for i in range(2, n):
                fib.append(fib[i-1] + fib[i-2])
            return fib
    '''
    
    # Step 1: Code quality analysis
    quality = workflow.add_text_task(
        name="Code Quality",
        prompt=f"Analyze code quality, efficiency, and style:\n```python\n{code_snippet}\n```",
        model="codellama",
        temperature=0.2
    )
    
    # Step 2: Security review
    security = workflow.add_text_task(
        name="Security Review",
        prompt=f"Review for security issues and vulnerabilities:\n```python\n{code_snippet}\n```",
        model="deepseek-coder",
        temperature=0.1
    )
    
    # Step 3: Generate documentation
    docs = workflow.add_text_task(
        name="Generate Docs",
        prompt=f"Generate comprehensive documentation:\n```python\n{code_snippet}\n```",
        model="codellama",
        temperature=0.5
    )
    
    # Step 4: Suggest improvements
    improvements = workflow.add_text_task(
        name="Improvements",
        prompt=f"""
        Based on the analyses, suggest improvements:
        Quality Issues: {{Code Quality.result}}
        Security Issues: {{Security Review.result}}
        
        Original code:
        ```python
        {code_snippet}
        ```
        """,
        model="mixtral",
        dependencies=["Code Quality", "Security Review"]
    )
    
    # Step 5: Generate refactored version
    refactor = workflow.add_text_task(
        name="Refactored Code",
        prompt=f"Refactor the code based on: {{{{Improvements.result}}}}",
        model="codellama:34b",
        dependencies=["Improvements"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🔍 Code Review Complete")
    print(f"Documentation:\n{result.results['Generate Docs']}")
    print(f"\nRefactored Code:\n{result.results['Refactored Code']}")
    
    await cluster.stop()


# ============================================
# Example 4: Content Generation Pipeline
# ============================================

async def content_generation_pipeline():
    """
    Generate blog post with research, writing, and editing stages
    """
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Content Generation")
    
    topic = "The impact of quantum computing on cryptography"
    
    # Research phase - parallel research tasks
    research_areas = [
        "current cryptographic methods",
        "quantum computing capabilities",
        "post-quantum cryptography",
        "timeline and practical implications"
    ]
    
    research_tasks = []
    for area in research_areas:
        task = workflow.add_text_task(
            name=f"Research: {area}",
            prompt=f"Research and summarize key points about {area} related to {topic}",
            model="llama3",
            temperature=0.5
        )
        research_tasks.append(task.name)
    
    # Outline generation based on research
    outline = workflow.add_text_task(
        name="Generate Outline",
        prompt=f"""
        Create a detailed blog post outline about '{topic}' based on research:
        """ + "\n".join([f"{{{{Research: {area}.result}}}}" for area in research_areas]),
        model="mixtral",
        dependencies=research_tasks
    )
    
    # Write sections in parallel
    sections = ["Introduction", "Main Body", "Implications", "Conclusion"]
    
    writing_tasks = []
    for section in sections:
        task = workflow.add_text_task(
            name=f"Write {section}",
            prompt=f"Write the {section} section based on outline: {{{{Generate Outline.result}}}}",
            model="llama3:70b",
            temperature=0.7,
            dependencies=["Generate Outline"]
        )
        writing_tasks.append(task.name)
    
    # Combine and edit
    final_post = workflow.add_text_task(
        name="Final Blog Post",
        prompt=f"""
        Combine and polish into a cohesive blog post:
        """ + "\n".join([f"{{{{Write {section}.result}}}}" for section in sections]),
        model="llama3:70b",
        temperature=0.6,
        dependencies=writing_tasks
    )
    
    # SEO optimization
    seo = workflow.add_text_task(
        name="SEO Optimization",
        prompt="Generate SEO title, meta description, and keywords for: {{Final Blog Post.result}}",
        model="mixtral",
        dependencies=["Final Blog Post"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📝 Content Generation Complete")
    print(f"Blog Post:\n{result.results['Final Blog Post'][:500]}...")
    print(f"\nSEO:\n{result.results['SEO Optimization']}")
    
    await cluster.stop()


# ============================================
# Example 5: Comparative Analysis Pipeline
# ============================================

async def comparative_analysis():
    """
    Compare responses from different models for the same prompt
    """
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Model Comparison")
    
    prompt = "Explain the concept of consciousness in 100 words"
    
    models = [
        ("llama3", 0.7),
        ("mixtral", 0.7),
        ("mistral", 0.7),
        ("phi", 0.7)
    ]
    
    # Get responses from each model
    response_tasks = []
    for model_name, temp in models:
        task = workflow.add_text_task(
            name=f"Response: {model_name}",
            prompt=prompt,
            model=model_name,
            temperature=temp
        )
        response_tasks.append(task.name)
    
    # Comparative analysis
    comparison = workflow.add_text_task(
        name="Comparative Analysis",
        prompt=f"""
        Compare and analyze these different explanations of consciousness:
        """ + "\n".join([f"{model}: {{{{Response: {model}.result}}}}" for model, _ in models]),
        model="llama3:70b",
        dependencies=response_tasks
    )
    
    # Pick best response
    best = workflow.add_text_task(
        name="Best Response",
        prompt="""
        Based on the analysis, which response was most accurate and clear?
        Analysis: {{Comparative Analysis.result}}
        """,
        model="mixtral",
        dependencies=["Comparative Analysis"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🔬 Model Comparison Complete")
    for model, _ in models:
        print(f"\n{model}:")
        print(result.results[f"Response: {model}"])
    print(f"\nAnalysis:\n{result.results['Comparative Analysis']}")
    
    await cluster.stop()


# ============================================
# Main
# ============================================

async def main():
    """Run example workflows"""
    
    examples = {
        "1": ("Document Analysis", document_analysis_pipeline),
        "2": ("Translation Pipeline", translation_pipeline),
        "3": ("Code Review", code_review_pipeline),
        "4": ("Content Generation", content_generation_pipeline),
        "5": ("Model Comparison", comparative_analysis)
    }
    
    print("🚀 Gleitzeit LLM Orchestration Examples")
    print("=" * 50)
    print("\nAvailable examples:")
    for key, (name, _) in examples.items():
        print(f"{key}. {name}")
    
    choice = input("\nSelect example (1-5): ").strip()
    
    if choice in examples:
        name, func = examples[choice]
        print(f"\n▶️ Running: {name}\n")
        await func()
    else:
        print("Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())