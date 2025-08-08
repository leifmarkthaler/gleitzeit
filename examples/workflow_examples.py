#!/usr/bin/env python3
"""
Advanced Workflow Examples for Gleitzeit Cluster

Demonstrates complex workflow patterns and use cases
"""

import asyncio
from gleitzeit_cluster import GleitzeitCluster
from gleitzeit_cluster.core.task import TaskType, TaskParameters
from gleitzeit_cluster.core.workflow import WorkflowErrorStrategy


async def content_marketing_pipeline():
    """Example: Content marketing analysis pipeline"""
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    try:
        print("📝 Content Marketing Analysis Pipeline")
        print("=" * 40)
        
        # Create comprehensive workflow
        workflow = cluster.create_workflow(
            name="content_marketing_pipeline",
            description="Analyze blog post content and generate marketing insights"
        )
        
        # Set error handling strategy
        workflow.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
        workflow.max_parallel_tasks = 5
        
        # Blog content analysis
        blog_content = """
        The Rise of Distributed AI Systems
        
        As artificial intelligence continues to evolve, distributed AI systems 
        are becoming increasingly important for handling large-scale workloads.
        These systems offer improved scalability, fault tolerance, and resource
        utilization compared to monolithic AI applications.
        
        Key benefits include:
        - Horizontal scalability across multiple machines
        - Better fault tolerance through redundancy  
        - More efficient resource utilization
        - Reduced latency through edge deployment
        """
        
        # Phase 1: Content Analysis (parallel)
        sentiment_task = workflow.add_text_task(
            name="analyze_sentiment",
            prompt=f"Analyze the sentiment and tone of this blog post:\n\n{blog_content}",
            model="llama3",
            temperature=0.3
        )
        
        readability_task = workflow.add_text_task(
            name="assess_readability", 
            prompt=f"Assess the readability and accessibility of this content for a technical audience:\n\n{blog_content}",
            model="llama3",
            temperature=0.4
        )
        
        seo_keywords_task = workflow.add_text_task(
            name="extract_seo_keywords",
            prompt=f"Extract SEO keywords and phrases from this blog post:\n\n{blog_content}",
            model="llama3",
            temperature=0.2
        )
        
        # Phase 2: Audience Analysis (depends on content analysis) 
        audience_analysis_task = workflow.add_text_task(
            name="analyze_target_audience",
            prompt="Based on the sentiment and readability analysis, identify the target audience demographics",
            model="llama3",
            dependencies=[sentiment_task.id, readability_task.id]
        )
        
        # Phase 3: Marketing Strategy (depends on audience analysis)
        social_media_task = workflow.add_text_task(
            name="generate_social_media_strategy",
            prompt="Create a social media promotion strategy based on the audience analysis",
            model="llama3",
            dependencies=[audience_analysis_task.id, seo_keywords_task.id]
        )
        
        email_campaign_task = workflow.add_text_task(
            name="design_email_campaign",
            prompt="Design an email marketing campaign strategy for this content",
            model="llama3", 
            dependencies=[audience_analysis_task.id]
        )
        
        # Phase 4: Performance Optimization
        optimization_task = workflow.add_text_task(
            name="content_optimization_recommendations",
            prompt="Provide content optimization recommendations based on all analyses",
            model="llama3",
            dependencies=[social_media_task.id, email_campaign_task.id]
        )
        
        # Execute workflow
        print("🚀 Executing marketing pipeline...")
        result = await cluster.execute_workflow(workflow)
        
        print("\n📊 Pipeline Results:")
        print(f"   Status: {result.status.value}")
        print(f"   Execution Time: {result.execution_time_seconds:.1f}s")
        print(f"   Tasks Completed: {result.completed_tasks}/{result.total_tasks}")
        
        if result.errors:
            print(f"   Errors: {len(result.errors)}")
            for task_id, error in result.errors.items():
                print(f"     - {task_id}: {error}")
                
        return result
        
    finally:
        await cluster.stop()


async def research_analysis_workflow():
    """Example: Multi-modal research analysis"""
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    try:
        print("\n🔬 Research Analysis Workflow")
        print("=" * 40)
        
        workflow = cluster.create_workflow(
            name="research_analysis",
            description="Analyze research papers with text and visual components"
        )
        
        # Research topic
        research_topic = "Quantum Computing Applications in Machine Learning"
        
        # Phase 1: Literature Review
        literature_review_task = workflow.add_text_task(
            name="literature_review",
            prompt=f"Conduct a comprehensive literature review on: {research_topic}",
            model="llama3",
            temperature=0.4
        )
        
        # Phase 2: Visual Analysis (parallel with literature review)
        research_diagrams = [
            "/path/to/quantum_circuit_diagram.png",
            "/path/to/ml_architecture_chart.png", 
            "/path/to/performance_comparison_graph.png"
        ]
        
        diagram_analysis_tasks = []
        for i, diagram_path in enumerate(research_diagrams):
            task = workflow.add_vision_task(
                name=f"analyze_diagram_{i+1}",
                prompt="Analyze this research diagram and explain the key concepts and relationships shown",
                image_path=diagram_path,
                model="llava",
                temperature=0.3
            )
            diagram_analysis_tasks.append(task)
        
        # Phase 3: Synthesis (depends on literature review and visual analysis)
        synthesis_dependencies = [literature_review_task.id] + [t.id for t in diagram_analysis_tasks]
        
        synthesis_task = workflow.add_text_task(
            name="synthesize_findings",
            prompt=f"Synthesize the literature review and visual analysis findings for {research_topic}",
            model="llama3",
            dependencies=synthesis_dependencies,
            temperature=0.5
        )
        
        # Phase 4: Generate Research Insights
        insights_task = workflow.add_text_task(
            name="generate_research_insights",
            prompt="Generate novel research insights and future directions based on the synthesis",
            model="llama3",
            dependencies=[synthesis_task.id],
            temperature=0.6
        )
        
        # Phase 5: Create Executive Summary
        executive_summary_task = workflow.add_text_task(
            name="create_executive_summary",
            prompt="Create a concise executive summary of all research findings",
            model="llama3",
            dependencies=[insights_task.id],
            temperature=0.3
        )
        
        # Execute workflow
        print("🚀 Executing research analysis...")
        result = await cluster.execute_workflow(workflow)
        
        print("\n📊 Research Analysis Results:")
        print(f"   Status: {result.status.value}")
        print(f"   Total Tasks: {result.total_tasks}")
        print(f"   Visual Analyses: {len(research_diagrams)}")
        print(f"   Synthesis Complete: {'✅' if synthesis_task.id in result.results else '❌'}")
        
        return result
        
    finally:
        await cluster.stop()


async def error_handling_example():
    """Example: Workflow error handling strategies"""
    
    cluster = GleitzeitCluster()
    await cluster.start()
    
    try:
        print("\n⚠️  Error Handling Examples")
        print("=" * 40)
        
        # Example 1: Stop on first error
        workflow1 = cluster.create_workflow(
            name="stop_on_error_example",
            description="Workflow that stops on first error"
        )
        workflow1.error_strategy = WorkflowErrorStrategy.STOP_ON_FIRST_ERROR
        
        # Add tasks that might fail
        task1 = workflow1.add_text_task(
            name="risky_task_1", 
            prompt="This might fail",
            model="nonexistent_model"  # This will fail
        )
        
        task2 = workflow1.add_text_task(
            name="dependent_task",
            prompt="This depends on the failed task",
            model="llama3",
            dependencies=[task1.id]
        )
        
        print("🚀 Testing STOP_ON_FIRST_ERROR strategy...")
        result1 = await cluster.execute_workflow(workflow1)
        print(f"   Result: {result1.status.value} ({result1.failed_tasks} failed)")
        
        # Example 2: Continue despite errors  
        workflow2 = cluster.create_workflow(
            name="continue_on_error_example",
            description="Workflow that continues despite errors"
        )
        workflow2.error_strategy = WorkflowErrorStrategy.CONTINUE_ON_ERROR
        
        # Add mix of tasks that will succeed and fail
        workflow2.add_text_task("failing_task", "Test", model="bad_model")
        workflow2.add_text_task("working_task_1", "Analyze AI trends", model="llama3") 
        workflow2.add_text_task("working_task_2", "Summarize benefits", model="llama3")
        
        print("\n🚀 Testing CONTINUE_ON_ERROR strategy...")
        result2 = await cluster.execute_workflow(workflow2)
        print(f"   Result: {result2.status.value} ({result2.completed_tasks} completed, {result2.failed_tasks} failed)")
        
        return result1, result2
        
    finally:
        await cluster.stop()


async def main():
    """Run all workflow examples"""
    
    print("🎯 Advanced Workflow Examples for Gleitzeit Cluster")
    print("=" * 60)
    
    # Run examples
    await content_marketing_pipeline()
    await research_analysis_workflow() 
    await error_handling_example()
    
    print("\n✅ All workflow examples completed!")
    print("\n💡 Key Patterns Demonstrated:")
    print("   ✅ Multi-phase workflows with dependencies")
    print("   ✅ Parallel task execution")
    print("   ✅ Mixed task types (text + vision)")  
    print("   ✅ Error handling strategies")
    print("   ✅ Complex business logic workflows")


if __name__ == "__main__":
    asyncio.run(main())