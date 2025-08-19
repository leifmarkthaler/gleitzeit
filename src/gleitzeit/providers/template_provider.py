"""
Workflow Template Provider for Gleitzeit

Provides pre-built workflow templates for common multi-step patterns like
research, code development, analysis, and chat workflows. This is a convenience
layer that generates structured workflows from simple parameters.

Key Features:
- Pre-built templates for common workflow patterns
- Automatic task dependency setup
- Parameter substitution between workflow steps  
- Simplified API for complex multi-step workflows
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

from gleitzeit.providers.base import ProtocolProvider
from gleitzeit.core import Task, Workflow, Priority
from gleitzeit.core.errors import ProviderError


class TemplateType(Enum):
    """Types of workflow templates"""
    RESEARCH = "research"
    CODE = "code"
    ANALYSIS = "analysis"
    CHAT = "chat"


@dataclass
class TemplateWorkflowResult:
    """Result of template workflow generation and execution"""
    template_type: str
    workflow_id: str
    status: str
    steps_planned: int
    execution_time: Optional[float] = None
    final_result: Optional[Dict] = None
    error: Optional[str] = None


class TemplateProvider(ProtocolProvider):
    """
    Provider that generates pre-built workflow templates for common patterns.
    
    This approach provides convenience templates for:
    1. Multi-step research workflows
    2. Code development workflows with testing and review
    3. Content analysis workflows
    4. Conversational workflows
    
    Templates are generated with proper dependencies and parameter substitution,
    then submitted to the execution engine for orchestration.
    """
    
    def __init__(
        self, 
        provider_id: str, 
        execution_engine=None,
        resource_manager=None,
        hub=None,
        **kwargs
    ):
        super().__init__(
            provider_id=provider_id,
            protocol_id="template/v1",
            name="WorkflowTemplateGenerator",
            description="Generates pre-built workflow templates for common patterns",
            resource_manager=resource_manager,
            hub=hub
        )
        self.execution_engine = execution_engine
        self.logger = logging.getLogger(__name__)
        
    def set_execution_engine(self, execution_engine):
        """Set execution engine for workflow submission"""
        self.execution_engine = execution_engine
    
    async def initialize(self):
        """Initialize the template provider"""
        self.logger.info(f"Initialized TemplateProvider: {self.provider_id}")
    
    def get_supported_methods(self) -> List[str]:
        """Get list of supported template methods"""
        return [
            "template/research",
            "template/code", 
            "template/analyze",
            "template/chat"
        ]
    
    async def handle_request(self, method: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle template workflow generation requests"""
        
        if not self.execution_engine:
            raise ProviderError("No execution engine available for template workflows")
        
        if method == "template/research":
            return await self._generate_research_workflow(parameters)
        elif method == "template/code":
            return await self._generate_code_workflow(parameters)
        elif method == "template/analyze":
            return await self._generate_analysis_workflow(parameters)
        elif method == "template/chat":
            return await self._generate_chat_workflow(parameters)
        else:
            raise ProviderError(f"Unknown template method: {method}")
    
    async def _generate_research_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a multi-step research workflow
        
        Creates a workflow that:
        1. Plans research strategy
        2. Gathers information from multiple sources
        3. Analyzes and synthesizes findings
        4. Generates comprehensive research report
        """
        topic = params["topic"]
        max_steps = params.get("max_steps", 5)
        depth = params.get("depth", "medium")
        
        workflow_id = f"template_research_{uuid.uuid4().hex[:8]}"
        
        self.logger.info(f"Generating research template workflow for: {topic}")
        
        # Create workflow tasks with dependencies
        tasks = []
        
        # Step 1: Create research plan
        tasks.append(Task(
            id="research_plan",
            name="Create Research Plan",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user", 
                    "content": f"""Create a detailed research plan for: {topic}
                    
Depth: {depth}
Maximum research steps: {max_steps}

Provide a structured plan with:
1. Key areas to investigate
2. Specific questions to answer
3. Types of information to gather
4. Research methodology

Be comprehensive but focused."""
                }],
                "temperature": 0.7
            },
            priority=Priority.HIGH
        ))
        
        # Step 2: General background research
        tasks.append(Task(
            id="background_research",
            name="Background Research", 
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["research_plan"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Based on this research plan: ${{research_plan.response}}
                    
Conduct background research on: {topic}

Provide:
- Historical context and evolution
- Key concepts and definitions  
- Current state of the field
- Major players and stakeholders"""
                }],
                "temperature": 0.6
            },
            priority=Priority.NORMAL
        ))
        
        # Step 3: Current trends and developments
        tasks.append(Task(
            id="current_trends",
            name="Current Trends Analysis",
            protocol="llm/v1", 
            method="llm/chat",
            dependencies=["background_research"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Building on this background: ${{background_research.response}}
                    
Research current trends and recent developments in: {topic}

Focus on:
- Latest innovations and breakthroughs
- Emerging patterns and directions
- Recent news and developments
- Future projections and predictions"""
                }],
                "temperature": 0.6
            },
            priority=Priority.NORMAL
        ))
        
        # Step 4: Analysis and implications
        tasks.append(Task(
            id="analysis",
            name="Analysis and Implications",
            protocol="llm/v1",
            method="llm/chat", 
            dependencies=["current_trends"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Analyze the research findings:
                    
Background: ${{background_research.response}}
Current Trends: ${{current_trends.response}}

Provide analysis of:
- Key insights and patterns
- Opportunities and challenges  
- Potential impacts and implications
- Critical success factors
- Risk assessment"""
                }],
                "temperature": 0.5
            },
            priority=Priority.NORMAL
        ))
        
        # Step 5: Comprehensive research report
        tasks.append(Task(
            id="final_report",
            name="Generate Research Report",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["research_plan", "background_research", "current_trends", "analysis"],
            params={
                "model": "llama3.2", 
                "messages": [{
                    "role": "user",
                    "content": f"""Create a comprehensive research report on: {topic}

Based on:
- Research Plan: ${{research_plan.response}}
- Background: ${{background_research.response}}  
- Current Trends: ${{current_trends.response}}
- Analysis: ${{analysis.response}}

Structure the report with:
1. Executive Summary
2. Background and Context
3. Current State and Trends
4. Key Findings and Insights
5. Implications and Recommendations
6. Conclusion

Make it professional, well-organized, and actionable."""
                }],
                "temperature": 0.4
            },
            priority=Priority.HIGH
        ))
        
        # Create and execute workflow
        workflow = Workflow(
            id=workflow_id,
            name=f"Research Template: {topic}",
            description=f"Multi-step research workflow for {topic}",
            tasks=tasks,
            metadata={
                "template_type": "research",
                "topic": topic,
                "depth": depth,
                "max_steps": max_steps
            }
        )
        
        # Submit workflow and wait for completion
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Get final result
        final_result = self.execution_engine.task_results.get("final_report")
        
        return {
            "template_type": "research",
            "workflow_id": workflow_id,
            "topic": topic,
            "status": "completed" if final_result and final_result.status == "completed" else "failed",
            "steps_planned": len(tasks),
            "execution_time": execution_time,
            "report": final_result.result.get("response") if final_result and final_result.result else None,
            "workflow_tasks": [task.id for task in tasks],
            "success": final_result and final_result.status == "completed"
        }
    
    async def _generate_code_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generate a code development workflow
        
        Creates a workflow that:
        1. Analyzes requirements and plans approach
        2. Generates initial code
        3. Tests and validates code  
        4. Refines and optimizes
        5. Generates documentation
        """
        task_description = params["task"]
        language = params.get("language", "python")
        
        workflow_id = f"template_code_{uuid.uuid4().hex[:8]}"
        
        self.logger.info(f"Generating code template workflow for: {task_description}")
        
        tasks = []
        
        # Step 1: Requirements analysis and planning
        tasks.append(Task(
            id="requirements_analysis",
            name="Requirements Analysis",
            protocol="llm/v1",
            method="llm/chat",
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Analyze the requirements for this coding task: {task_description}

Language: {language}

Provide:
1. Requirements breakdown and clarification
2. Technical approach and architecture
3. Key components and functions needed
4. Potential challenges and considerations
5. Implementation strategy"""
                }],
                "temperature": 0.3
            },
            priority=Priority.HIGH
        ))
        
        # Step 2: Generate initial code
        tasks.append(Task(
            id="code_generation", 
            name="Generate Code",
            protocol="llm/v1",
            method="llm/chat",
            dependencies=["requirements_analysis"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Based on this analysis: ${{requirements_analysis.response}}

Generate {language} code for: {task_description}

Requirements:
- Clean, well-commented code
- Follow best practices for {language}
- Include error handling
- Make it production-ready
- Add docstrings/comments

Provide only the code with clear formatting."""
                }],
                "temperature": 0.2
            },
            priority=Priority.NORMAL
        ))
        
        # Step 3: Code testing (using Python provider if available)
        if language.lower() == "python":
            tasks.append(Task(
                id="code_testing",
                name="Test Code",
                protocol="python/v1", 
                method="python/execute",
                dependencies=["code_generation"],
                params={
                    "code": "${code_generation.response}",
                    "timeout": 30
                },
                priority=Priority.NORMAL
            ))
        
        # Step 4: Code review and optimization
        dependencies = ["code_generation"]
        if language.lower() == "python":
            dependencies.append("code_testing")
            
        tasks.append(Task(
            id="code_review",
            name="Code Review and Optimization", 
            protocol="llm/v1",
            method="llm/chat",
            dependencies=dependencies,
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user",
                    "content": f"""Review and optimize this {language} code:

Code: ${{code_generation.response}}
{"Test Results: ${code_testing.result}" if language.lower() == "python" else ""}

Provide:
1. Code quality assessment
2. Optimization suggestions  
3. Best practices review
4. Security considerations
5. Final optimized version (if improvements needed)"""
                }],
                "temperature": 0.3
            },
            priority=Priority.NORMAL
        ))
        
        # Step 5: Generate documentation
        tasks.append(Task(
            id="documentation",
            name="Generate Documentation",
            protocol="llm/v1", 
            method="llm/chat",
            dependencies=["code_review"],
            params={
                "model": "llama3.2",
                "messages": [{
                    "role": "user", 
                    "content": f"""Create comprehensive documentation for this {language} code:

Original Task: {task_description}
Code: ${{code_generation.response}}
Review: ${{code_review.response}}

Generate:
1. Overview and purpose
2. Installation/setup instructions
3. Usage examples
4. API documentation (if applicable)
5. Testing instructions
6. Contributing guidelines

Make it clear and user-friendly."""
                }],
                "temperature": 0.4
            },
            priority=Priority.NORMAL
        ))
        
        # Create and execute workflow
        workflow = Workflow(
            id=workflow_id,
            name=f"Agent Code: {task_description[:50]}",
            description=f"Autonomous code development workflow",
            tasks=tasks,
            metadata={
                "agent_type": "code",
                "task": task_description,
                "language": language
            }
        )
        
        # Submit workflow and wait for completion
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        # Get results
        code_result = self.execution_engine.task_results.get("code_generation")
        review_result = self.execution_engine.task_results.get("code_review")
        docs_result = self.execution_engine.task_results.get("documentation")
        test_result = self.execution_engine.task_results.get("code_testing") if language.lower() == "python" else None
        
        return {
            "template_type": "code",
            "workflow_id": workflow_id,
            "task": task_description,
            "language": language,
            "status": "completed" if code_result and code_result.status == "completed" else "failed",
            "steps_planned": len(tasks),
            "execution_time": execution_time,
            "code": code_result.result.get("response") if code_result and code_result.result else None,
            "review": review_result.result.get("response") if review_result and review_result.result else None,
            "documentation": docs_result.result.get("response") if docs_result and docs_result.result else None,
            "test_result": test_result.result if test_result and test_result.result else None,
            "workflow_tasks": [task.id for task in tasks],
            "success": code_result and code_result.status == "completed"
        }
    
    async def _generate_analysis_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a content analysis workflow"""
        content = params["content"]
        question = params.get("question", "Provide a comprehensive analysis")
        
        workflow_id = f"template_analysis_{uuid.uuid4().hex[:8]}"
        
        # Simple single-step analysis for now
        tasks = [
            Task(
                id="content_analysis",
                name="Content Analysis",
                protocol="llm/v1",
                method="llm/chat",
                params={
                    "model": "llama3.2",
                    "messages": [{
                        "role": "user",
                        "content": f"""Analyze this content and answer the question:

Content:
{content}

Question: {question}

Provide a thorough, structured analysis."""
                    }],
                    "temperature": 0.6
                },
                priority=Priority.NORMAL
            )
        ]
        
        workflow = Workflow(
            id=workflow_id,
            name="Agent Analysis",
            tasks=tasks,
            metadata={"template_type": "analysis"}
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        result = self.execution_engine.task_results.get("content_analysis")
        
        return {
            "template_type": "analysis",
            "workflow_id": workflow_id,
            "status": "completed" if result and result.status == "completed" else "failed",
            "execution_time": execution_time,
            "analysis": result.result.get("response") if result and result.result else None,
            "success": result and result.status == "completed"
        }
    
    async def _generate_chat_workflow(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Generate a simple chat workflow"""
        message = params["message"]
        session_id = params.get("session_id")
        
        workflow_id = f"template_chat_{uuid.uuid4().hex[:8]}"
        
        # Simple single-step chat for now
        tasks = [
            Task(
                id="chat_response",
                name="Chat Response",
                protocol="llm/v1",
                method="llm/chat",
                params={
                    "model": "llama3.2",
                    "messages": [{
                        "role": "user",
                        "content": message
                    }],
                    "temperature": 0.8
                },
                priority=Priority.NORMAL
            )
        ]
        
        workflow = Workflow(
            id=workflow_id,
            name="Agent Chat",
            tasks=tasks,
            metadata={"template_type": "chat", "session_id": session_id}
        )
        
        # Execute workflow
        start_time = datetime.now()
        await self.execution_engine.submit_workflow(workflow)
        await self.execution_engine._execute_workflow(workflow)
        execution_time = (datetime.now() - start_time).total_seconds()
        
        result = self.execution_engine.task_results.get("chat_response")
        
        return {
            "template_type": "chat",
            "workflow_id": workflow_id,
            "session_id": session_id,
            "status": "completed" if result and result.status == "completed" else "failed",
            "execution_time": execution_time,
            "response": result.result.get("response") if result and result.result else None,
            "success": result and result.status == "completed"
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Health check for the template provider"""
        return {
            "status": "healthy",
            "execution_engine_available": self.execution_engine is not None,
            "supported_methods": len(self.get_supported_methods())
        }
    
    async def shutdown(self):
        """Clean shutdown of the template provider"""
        self.logger.info(f"TemplateProvider {self.provider_id} shut down")