#!/usr/bin/env python
"""
Demo script for AgentHub functionality

This demonstrates how to use the AgentHub to:
1. Create and manage agent instances
2. Execute research tasks
3. Generate code
4. Have interactive conversations
"""

import asyncio
import logging
from datetime import datetime
import uuid

from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentType, AgentConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def setup_environment():
    """Set up the resource manager with necessary hubs"""
    logger.info("Setting up resource environment...")
    
    # Create resource manager
    resource_manager = ResourceManager("demo-manager")
    await resource_manager.start()
    
    # Create Ollama hub (required for LLM calls)
    logger.info("Creating Ollama hub...")
    ollama_hub = await resource_manager.create_ollama_hub(
        hub_id="ollama",
        auto_discover=True
    )
    
    # Create Agent hub
    logger.info("Creating Agent hub...")
    agent_hub = await resource_manager.create_agent_hub(
        hub_id="agent",
        max_agents=5
    )
    
    return resource_manager, agent_hub


async def demo_research_agent(agent_hub):
    """Demonstrate research agent capabilities"""
    print("\n" + "="*60)
    print("RESEARCH AGENT DEMO")
    print("="*60)
    
    # Execute research task
    logger.info("Starting research on machine learning...")
    result = await agent_hub.execute_agent_task(
        method="research",
        parameters={
            "topic": "Recent advances in transformer neural networks",
            "max_steps": 3  # Limit steps for demo
        }
    )
    
    print(f"\n📚 Research Report:")
    print("-" * 40)
    print(result.get("report", "No report generated")[:1000])  # Truncate for display
    print(f"\n✅ Steps executed: {result.get('steps_executed', 0)}")
    print(f"📝 Session ID: {result.get('session_id', 'N/A')}")
    
    return result


async def demo_code_agent(agent_hub):
    """Demonstrate code generation agent"""
    print("\n" + "="*60)
    print("CODE GENERATION AGENT DEMO")
    print("="*60)
    
    # Generate code
    logger.info("Generating Python code...")
    result = await agent_hub.execute_agent_task(
        method="code",
        parameters={
            "task": "Create a Python function that calculates the Fibonacci sequence using memoization",
            "language": "python"
        }
    )
    
    print(f"\n💻 Generated Code:")
    print("-" * 40)
    print(result.get("code", "No code generated"))
    
    print(f"\n📖 Explanation:")
    print("-" * 40)
    print(result.get("explanation", "No explanation provided"))
    
    if result.get("test_result"):
        print(f"\n🧪 Test Result: {result['test_result']}")
    
    return result


async def demo_chat_agent(agent_hub):
    """Demonstrate conversational agent with memory"""
    print("\n" + "="*60)
    print("CONVERSATIONAL AGENT DEMO")
    print("="*60)
    
    session_id = str(uuid.uuid4())
    print(f"📍 Session ID: {session_id}\n")
    
    # Conversation flow
    conversations = [
        "Hello! Can you explain what neural networks are?",
        "What are the main types of neural networks?",
        "Can you give me a simple example of how to create one?"
    ]
    
    for i, message in enumerate(conversations, 1):
        print(f"\n👤 User {i}: {message}")
        
        result = await agent_hub.execute_agent_task(
            method="chat",
            parameters={"message": message},
            session_id=session_id  # Maintain session for context
        )
        
        response = result.get("response", "No response")
        print(f"🤖 Agent {i}: {response[:500]}")  # Truncate long responses
        
        if result.get("tools_used"):
            print(f"   🔧 Tools used: Yes")
    
    return session_id


async def demo_agent_management(agent_hub):
    """Demonstrate agent instance management"""
    print("\n" + "="*60)
    print("AGENT MANAGEMENT DEMO")
    print("="*60)
    
    # Get current status
    status = await agent_hub.get_agent_status()
    
    print(f"\n📊 Agent Hub Status:")
    print(f"   Total agents: {status['total_agents']}/{status['max_agents']}")
    print(f"   Active agents:")
    
    for agent in status["agents"]:
        print(f"      - {agent['id']} ({agent['type']})")
        print(f"        Model: {agent['model']}")
        print(f"        Requests: {agent['metrics']['total_requests']}")
        print(f"        Sessions: {agent['sessions']}")
    
    # Clean up old sessions
    logger.info("Cleaning up old sessions...")
    cleaned = await agent_hub.cleanup_sessions(max_age_seconds=1800)  # 30 minutes
    print(f"\n🧹 Cleaned up {cleaned} expired sessions")
    
    return status


async def main():
    """Main demo function"""
    print("\n" + "="*60)
    print("GLEITZEIT AGENT HUB DEMONSTRATION")
    print("="*60)
    
    try:
        # Setup environment
        resource_manager, agent_hub = await setup_environment()
        
        # Run demos
        print("\nStarting agent demonstrations...")
        
        # 1. Research Agent
        research_result = await demo_research_agent(agent_hub)
        await asyncio.sleep(1)  # Brief pause between demos
        
        # 2. Code Generation Agent
        code_result = await demo_code_agent(agent_hub)
        await asyncio.sleep(1)
        
        # 3. Conversational Agent
        session_id = await demo_chat_agent(agent_hub)
        await asyncio.sleep(1)
        
        # 4. Agent Management
        status = await demo_agent_management(agent_hub)
        
        # Summary
        print("\n" + "="*60)
        print("DEMO COMPLETE")
        print("="*60)
        print(f"\n✅ Successfully demonstrated:")
        print(f"   • Research agent with {research_result.get('steps_executed', 0)} steps")
        print(f"   • Code generation in {code_result.get('language', 'unknown')} language")
        print(f"   • Conversational agent with session {session_id[:8]}...")
        print(f"   • Agent management with {status['total_agents']} active agents")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise
    
    finally:
        # Cleanup
        logger.info("Shutting down...")
        await agent_hub.stop()
        await resource_manager.stop()
        print("\n👋 Demo completed successfully!")


if __name__ == "__main__":
    # Note: This demo requires Ollama to be running locally
    print("\n⚠️  Prerequisites:")
    print("   • Ollama must be running (ollama serve)")
    print("   • llama3.2 model should be available")
    print("\n" + "="*60)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Demo interrupted by user")
    except Exception as e:
        print(f"\n\n❌ Demo failed: {e}")
        print("\nPlease ensure Ollama is running and accessible")