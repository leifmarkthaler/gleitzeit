#!/usr/bin/env python3
"""
Real-World Workflow Examples

Production-ready examples showing how Gleitzeit orchestrates
complex workflows in real scenarios.
"""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.decorators import gleitzeit_task, start_task_service
from gleitzeit_cluster.execution.ollama_endpoint_manager import EndpointConfig, LoadBalancingStrategy


# ============================================
# Customer Support Ticket Processing
# ============================================

@gleitzeit_task(category="support")
def parse_ticket(raw_ticket: str) -> Dict:
    """Parse customer support ticket"""
    # In production, this would parse email/form data
    return {
        "ticket_id": "TICK-2024-001",
        "customer_id": "CUST-123",
        "timestamp": datetime.now().isoformat(),
        "subject": "Product not working as expected",
        "body": raw_ticket,
        "priority": None,  # To be determined
        "category": None   # To be determined
    }


@gleitzeit_task(category="support")
def lookup_customer_history(customer_id: str) -> Dict:
    """Look up customer history from database"""
    # Mock database lookup
    return {
        "customer_since": "2020-01-15",
        "total_purchases": 5,
        "support_tickets": 2,
        "satisfaction_score": 4.5,
        "is_premium": True
    }


@gleitzeit_task(category="support")
def generate_response_template(category: str, sentiment: str) -> str:
    """Generate appropriate response template"""
    templates = {
        ("technical", "negative"): "We sincerely apologize for the technical difficulties...",
        ("billing", "negative"): "We understand your concern regarding billing...",
        ("technical", "neutral"): "Thank you for reaching out about this technical matter...",
        ("billing", "neutral"): "Thank you for your billing inquiry..."
    }
    return templates.get((category, sentiment), "Thank you for contacting support...")


async def customer_support_workflow():
    """
    Complete customer support ticket processing workflow
    """
    
    cluster = GleitzeitCluster(
        ollama_endpoints=[
            EndpointConfig("http://localhost:11434", priority=1)
        ]
    )
    await cluster.start()
    
    workflow = cluster.create_workflow("Support Ticket Processing")
    
    raw_ticket = """
    My premium subscription isn't giving me access to the advanced features.
    I've tried logging out and back in, but it still shows me as a free user.
    This is really frustrating as I'm paying for features I can't use!
    Order ID: ORD-2024-4567
    """
    
    # Step 1: Parse ticket
    parse = workflow.add_external_task(
        name="Parse Ticket",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "parse_ticket",
            "args": [raw_ticket]
        }
    )
    
    # Step 2: Analyze sentiment and categorize
    analyze = workflow.add_text_task(
        name="Analyze Ticket",
        prompt=f"""
        Analyze this support ticket and provide:
        1. Category (technical, billing, feature_request, other)
        2. Sentiment (positive, neutral, negative)
        3. Urgency (low, medium, high)
        4. Key issues identified
        
        Ticket: {raw_ticket}
        
        Respond in JSON format.
        """,
        model="llama3",
        temperature=0.3,
        dependencies=["Parse Ticket"]
    )
    
    # Step 3: Lookup customer history
    history = workflow.add_external_task(
        name="Customer History",
        external_task_type="python_execution",
        service_name="Python Tasks",
        external_parameters={
            "function_name": "lookup_customer_history",
            "args": ["{{Parse Ticket.result.customer_id}}"]
        },
        dependencies=["Parse Ticket"]
    )
    
    # Step 4: Generate solution
    solution = workflow.add_text_task(
        name="Generate Solution",
        prompt="""
        Based on the ticket analysis and customer history, provide:
        1. Root cause analysis
        2. Step-by-step solution
        3. Preventive measures
        
        Analysis: {{Analyze Ticket.result}}
        Customer History: {{Customer History.result}}
        """,
        model="mixtral",
        temperature=0.4,
        dependencies=["Analyze Ticket", "Customer History"]
    )
    
    # Step 5: Draft response
    response = workflow.add_text_task(
        name="Draft Response",
        prompt=f"""
        Draft a professional, empathetic customer support response.
        
        Customer is premium: {{{{Customer History.result.is_premium}}}}
        Issue: {raw_ticket}
        Solution: {{{{Generate Solution.result}}}}
        
        The response should:
        1. Acknowledge the frustration
        2. Provide clear solution steps
        3. Offer compensation if appropriate
        4. Include follow-up actions
        """,
        model="llama3:70b",
        temperature=0.6,
        dependencies=["Generate Solution", "Customer History"]
    )
    
    # Step 6: Quality check
    quality = workflow.add_text_task(
        name="Quality Check",
        prompt="""
        Review this support response for:
        1. Professionalism
        2. Completeness
        3. Accuracy
        4. Empathy
        
        Response: {{Draft Response.result}}
        
        Provide a quality score (1-10) and any necessary improvements.
        """,
        model="llama3",
        dependencies=["Draft Response"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🎫 Support Ticket Processed")
    print(f"\nDraft Response:\n{result.results['Draft Response']}")
    print(f"\nQuality Check:\n{result.results['Quality Check']}")
    
    await cluster.stop()


# ============================================
# Research Paper Analysis Pipeline
# ============================================

async def research_paper_analysis():
    """
    Analyze research papers with multiple specialized models
    """
    
    cluster = GleitzeitCluster(
        ollama_strategy=LoadBalancingStrategy.LEAST_LOADED
    )
    await cluster.start()
    
    workflow = cluster.create_workflow("Research Paper Analysis")
    
    paper_abstract = """
    We present a novel approach to distributed machine learning that achieves
    linear scalability while maintaining model accuracy. Our method uses
    asynchronous gradient updates with momentum correction and adaptive
    learning rates. Experiments on ImageNet and COCO datasets show 3.2x
    speedup over state-of-the-art methods with only 0.5% accuracy loss.
    We also introduce a new communication protocol that reduces network
    overhead by 67% compared to traditional parameter servers.
    """
    
    # Parallel analysis by different models
    analyses = [
        ("Technical Depth", "Analyze the technical contributions and novelty"),
        ("Methodology", "Evaluate the research methodology and experimental design"),
        ("Impact", "Assess potential impact and applications"),
        ("Limitations", "Identify limitations and potential issues"),
        ("Related Work", "Suggest related papers and research directions")
    ]
    
    analysis_tasks = []
    for aspect, prompt_suffix in analyses:
        task = workflow.add_text_task(
            name=f"Analyze {aspect}",
            prompt=f"""
            Research paper abstract: {paper_abstract}
            
            Task: {prompt_suffix}
            Provide detailed analysis.
            """,
            model="mixtral" if aspect == "Technical Depth" else "llama3",
            temperature=0.4
        )
        analysis_tasks.append(task.name)
    
    # Synthesize comprehensive review
    review = workflow.add_text_task(
        name="Comprehensive Review",
        prompt=f"""
        Synthesize a comprehensive peer review based on these analyses:
        """ + "\n".join([f"{aspect}: {{{{{task}.result}}}}" for task, (aspect, _) in zip(analysis_tasks, analyses)]),
        model="llama3:70b",
        temperature=0.5,
        dependencies=analysis_tasks
    )
    
    # Generate questions for authors
    questions = workflow.add_text_task(
        name="Review Questions",
        prompt="""
        Based on the comprehensive review, generate 5 critical questions
        for the authors that would strengthen the paper:
        
        Review: {{Comprehensive Review.result}}
        """,
        model="mixtral",
        dependencies=["Comprehensive Review"]
    )
    
    # Recommendation
    recommendation = workflow.add_text_task(
        name="Publication Recommendation",
        prompt="""
        Based on all analyses, provide publication recommendation:
        1. Accept/Reject/Major Revision/Minor Revision
        2. Justification
        3. Required improvements
        
        Review: {{Comprehensive Review.result}}
        """,
        model="llama3:70b",
        temperature=0.3,
        dependencies=["Comprehensive Review"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📚 Research Paper Analysis Complete")
    print(f"\nComprehensive Review:\n{result.results['Comprehensive Review'][:500]}...")
    print(f"\nRecommendation:\n{result.results['Publication Recommendation']}")
    
    await cluster.stop()


# ============================================
# Social Media Content Pipeline
# ============================================

@gleitzeit_task(category="social")
def extract_hashtags(content: str) -> List[str]:
    """Extract and validate hashtags"""
    import re
    hashtags = re.findall(r'#\w+', content)
    return hashtags[:10]  # Limit to 10 hashtags


@gleitzeit_task(category="social")
def check_content_policy(content: str) -> Dict:
    """Check content against platform policies"""
    # Simplified policy check
    prohibited_words = ["spam", "fake", "scam"]
    issues = [word for word in prohibited_words if word in content.lower()]
    
    return {
        "compliant": len(issues) == 0,
        "issues": issues,
        "checked_at": datetime.now().isoformat()
    }


async def social_media_pipeline():
    """
    Create and optimize social media content across platforms
    """
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    workflow = cluster.create_workflow("Social Media Content")
    
    topic = "Launch of new AI-powered productivity app"
    target_audience = "Tech professionals and startup founders"
    
    # Generate content for different platforms
    platforms = [
        ("Twitter", 280, "concise and engaging with relevant hashtags"),
        ("LinkedIn", 1300, "professional and insightful"),
        ("Instagram", 2200, "visual description with emoji and hashtags"),
        ("TikTok", 150, "trendy and casual with call-to-action")
    ]
    
    content_tasks = []
    for platform, char_limit, style in platforms:
        task = workflow.add_text_task(
            name=f"{platform} Content",
            prompt=f"""
            Create {platform} post about: {topic}
            Target audience: {target_audience}
            Style: {style}
            Character limit: {char_limit}
            Include relevant hashtags and emoji where appropriate.
            """,
            model="llama3",
            temperature=0.7
        )
        content_tasks.append(task.name)
    
    # Extract hashtags from all content
    hashtag_tasks = []
    for platform, _, _ in platforms:
        task = workflow.add_external_task(
            name=f"{platform} Hashtags",
            external_task_type="python_execution",
            service_name="Python Tasks",
            external_parameters={
                "function_name": "extract_hashtags",
                "args": [f"{{{{{platform} Content.result}}}}"]
            },
            dependencies=[f"{platform} Content"]
        )
        hashtag_tasks.append(task.name)
    
    # Policy compliance check
    policy_tasks = []
    for platform, _, _ in platforms:
        task = workflow.add_external_task(
            name=f"{platform} Policy Check",
            external_task_type="python_execution",
            service_name="Python Tasks",
            external_parameters={
                "function_name": "check_content_policy",
                "args": [f"{{{{{platform} Content.result}}}}"]
            },
            dependencies=[f"{platform} Content"]
        )
        policy_tasks.append(task.name)
    
    # Generate unified campaign strategy
    strategy = workflow.add_text_task(
        name="Campaign Strategy",
        prompt=f"""
        Based on the content created for all platforms, develop a unified campaign strategy:
        
        Twitter: {{{{Twitter Content.result}}}}
        LinkedIn: {{{{LinkedIn Content.result}}}}
        Instagram: {{{{Instagram Content.result}}}}
        TikTok: {{{{TikTok Content.result}}}}
        
        Include:
        1. Posting schedule
        2. Cross-platform promotion ideas
        3. Engagement tactics
        4. Success metrics
        """,
        model="mixtral",
        temperature=0.6,
        dependencies=content_tasks
    )
    
    # A/B test variations
    ab_test = workflow.add_text_task(
        name="A/B Test Variants",
        prompt="""
        Create A/B test variations for the Twitter content:
        Original: {{Twitter Content.result}}
        
        Generate 2 alternative versions with different:
        1. Call-to-action
        2. Tone
        3. Hashtag strategy
        """,
        model="llama3",
        dependencies=["Twitter Content"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("📱 Social Media Content Pipeline Complete")
    for platform, _, _ in platforms:
        print(f"\n{platform}:")
        print(result.results[f"{platform} Content"])
        print(f"Policy Check: {result.results[f'{platform} Policy Check']}")
    print(f"\nCampaign Strategy:\n{result.results['Campaign Strategy'][:500]}...")
    
    await cluster.stop()


# ============================================
# E-commerce Product Launch
# ============================================

async def ecommerce_product_launch():
    """
    Complete product launch workflow for e-commerce
    """
    
    cluster = GleitzeitCluster(
        ollama_endpoints=[
            EndpointConfig("http://localhost:11434", priority=1)
        ]
    )
    await cluster.start()
    
    workflow = cluster.create_workflow("Product Launch")
    
    product_info = {
        "name": "SmartHome Hub Pro",
        "category": "IoT/Smart Home",
        "price": 199.99,
        "features": [
            "Voice control",
            "Works with 500+ devices",
            "AI-powered automation",
            "Energy monitoring"
        ]
    }
    
    # Generate product description
    description = workflow.add_text_task(
        name="Product Description",
        prompt=f"""
        Write compelling e-commerce product description for:
        {json.dumps(product_info, indent=2)}
        
        Include: benefits, use cases, technical specs
        """,
        model="llama3:70b",
        temperature=0.6
    )
    
    # SEO optimization
    seo = workflow.add_text_task(
        name="SEO Optimization",
        prompt=f"""
        Generate SEO-optimized content for:
        Product: {product_info['name']}
        Description: {{{{Product Description.result}}}}
        
        Provide:
        1. Title tag (60 chars)
        2. Meta description (160 chars)
        3. 10 target keywords
        4. URL slug
        """,
        model="mixtral",
        dependencies=["Product Description"]
    )
    
    # Email campaign
    email = workflow.add_text_task(
        name="Launch Email",
        prompt=f"""
        Create product launch email campaign:
        Product: {product_info['name']}
        Price: ${product_info['price']}
        
        Include:
        1. Subject line (A/B test variants)
        2. Preview text
        3. Email body with CTAs
        4. Segmentation strategy
        """,
        model="llama3",
        temperature=0.7
    )
    
    # Ad copy for different platforms
    ad_platforms = ["Google Ads", "Facebook", "Amazon"]
    
    ad_tasks = []
    for platform in ad_platforms:
        task = workflow.add_text_task(
            name=f"{platform} Ad Copy",
            prompt=f"""
            Create {platform} ad copy for:
            {product_info['name']} - ${product_info['price']}
            
            Platform requirements:
            - Google Ads: Headlines (30 chars), Descriptions (90 chars)
            - Facebook: Primary text, headline, description
            - Amazon: Title, bullet points, search terms
            """,
            model="llama3",
            temperature=0.6
        )
        ad_tasks.append(task.name)
    
    # Competitive analysis
    competitive = workflow.add_text_task(
        name="Competitive Analysis",
        prompt=f"""
        Analyze competitive positioning for {product_info['name']}:
        
        1. Key differentiators
        2. Pricing strategy justification
        3. Target market segments
        4. Potential objections and responses
        """,
        model="mixtral",
        temperature=0.5
    )
    
    # Launch checklist
    checklist = workflow.add_text_task(
        name="Launch Checklist",
        prompt=f"""
        Generate comprehensive product launch checklist based on:
        - Product description: {{{{Product Description.result}}}}
        - SEO plan: {{{{SEO Optimization.result}}}}
        - Email campaign: {{{{Launch Email.result}}}}
        - Competitive analysis: {{{{Competitive Analysis.result}}}}
        
        Organize by: Pre-launch, Launch day, Post-launch
        """,
        model="llama3:70b",
        dependencies=["Product Description", "SEO Optimization", "Launch Email", "Competitive Analysis"]
    )
    
    workflow_id = await cluster.submit_workflow(workflow)
    result = await cluster.wait_for_workflow(workflow_id)
    
    print("🚀 E-commerce Product Launch Complete")
    print(f"\nProduct Description:\n{result.results['Product Description'][:300]}...")
    print(f"\nSEO:\n{result.results['SEO Optimization']}")
    print(f"\nLaunch Checklist:\n{result.results['Launch Checklist'][:500]}...")
    
    await cluster.stop()


# ============================================
# Main
# ============================================

async def main():
    """Run real-world workflow examples"""
    
    # Start Python task service for decorated functions
    print("📌 Starting Python task service...")
    task_service = asyncio.create_task(start_task_service(auto_discover=False))
    await asyncio.sleep(2)
    
    examples = {
        "1": ("Customer Support Ticket", customer_support_workflow),
        "2": ("Research Paper Analysis", research_paper_analysis),
        "3": ("Social Media Campaign", social_media_pipeline),
        "4": ("E-commerce Product Launch", ecommerce_product_launch)
    }
    
    print("\n🌟 Real-World Workflow Examples")
    print("=" * 50)
    print("\nAvailable workflows:")
    for key, (name, _) in examples.items():
        print(f"{key}. {name}")
    
    choice = input("\nSelect workflow (1-4): ").strip()
    
    if choice in examples:
        name, func = examples[choice]
        print(f"\n▶️ Running: {name}\n")
        await func()
    else:
        print("Invalid choice")


if __name__ == "__main__":
    asyncio.run(main())