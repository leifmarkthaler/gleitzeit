#!/usr/bin/env python
"""
Real test of AgentHub with actual Ollama integration

This test requires:
- Ollama to be running locally (ollama serve)
- llama3.2 model to be available
"""

import asyncio
import logging
import sys
from datetime import datetime

# Add src to path for imports
sys.path.insert(0, '/Users/leifmarkthaler/github/gleitzeit/src')

from gleitzeit.hub.resource_manager import ResourceManager
from gleitzeit.hub.agent_hub import AgentType

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_real_agent_workflow():
    """Test agent workflow with real Ollama"""
    
    print("\n" + "="*60)
    print("REAL AGENT WORKFLOW TEST")
    print("="*60)
    
    resource_manager = None
    agent_hub = None
    
    try:
        # Create resource manager
        logger.info("Creating resource manager...")
        resource_manager = ResourceManager("test-manager")
        await resource_manager.start()
        
        # Create Ollama hub
        logger.info("Creating Ollama hub...")
        ollama_hub = await resource_manager.create_ollama_hub(
            hub_id="ollama",
            auto_discover=True
        )
        
        # Verify Ollama is available
        logger.info("Checking Ollama availability...")
        ollama_instances = await ollama_hub.list_instances()
        if not ollama_instances:
            print("❌ No Ollama instances found. Please ensure Ollama is running.")
            return False
        
        print(f"✅ Found {len(ollama_instances)} Ollama instance(s)")
        for instance in ollama_instances:
            print(f"   - {instance.name} at {instance.endpoint}")
        
        # Create Agent hub
        logger.info("Creating Agent hub...")
        agent_hub = await resource_manager.create_agent_hub(
            hub_id="agent",
            max_agents=3
        )
        
        print(f"✅ Agent hub created with max_agents=3")
        
        # Test 1: Simple Research Task
        print("\n" + "-"*40)
        print("TEST 1: Research Agent")
        print("-"*40)
        
        logger.info("Executing research task...")
        research_result = await agent_hub.execute_agent_task(
            method="research",
            parameters={
                "topic": "What are the key benefits of Python programming?",
                "max_steps": 2  # Keep it short for testing
            }
        )
        
        print(f"\n📚 Research completed:")
        print(f"   - Success: {research_result.get('success', False)}")
        print(f"   - Steps executed: {research_result.get('steps_executed', 0)}")
        print(f"   - Session ID: {research_result.get('session_id', 'N/A')}")
        
        if research_result.get('report'):
            print(f"\n📄 Report Preview (first 500 chars):")
            print(research_result['report'][:500])
        
        # Test 2: Code Generation
        print("\n" + "-"*40)
        print("TEST 2: Code Generation Agent")
        print("-"*40)
        
        logger.info("Executing code generation task...")
        code_result = await agent_hub.execute_agent_task(
            method="code",
            parameters={
                "task": "Write a Python function that calculates the factorial of a number",
                "language": "python"
            }
        )
        
        print(f"\n💻 Code generation completed:")
        print(f"   - Language: {code_result.get('language', 'N/A')}")
        
        if code_result.get('code'):
            print(f"\n📝 Generated Code:")
            print(code_result['code'])
        
        if code_result.get('explanation'):
            print(f"\n📖 Explanation (first 300 chars):")
            print(code_result['explanation'][:300])
        
        # Test 3: Chat with Session
        print("\n" + "-"*40)
        print("TEST 3: Chat Agent with Session")
        print("-"*40)
        
        session_id = "test_session_001"
        
        # First message
        logger.info("Sending first chat message...")
        chat1 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "Hello! Can you tell me about recursion?",
                "session_id": session_id
            }
        )
        
        print(f"\n💬 Chat 1:")
        print(f"   User: Hello! Can you tell me about recursion?")
        print(f"   Agent: {chat1.get('response', 'No response')[:300]}...")
        
        # Second message (should remember context)
        logger.info("Sending follow-up message...")
        chat2 = await agent_hub.execute_agent_task(
            method="chat",
            parameters={
                "message": "Can you give me a simple example?",
                "session_id": session_id
            }
        )
        
        print(f"\n💬 Chat 2:")
        print(f"   User: Can you give me a simple example?")
        print(f"   Agent: {chat2.get('response', 'No response')[:300]}...")
        
        # Test 4: Analysis
        print("\n" + "-"*40)
        print("TEST 4: Analysis Agent")
        print("-"*40)
        
        logger.info("Executing analysis task...")
        analysis_result = await agent_hub.execute_agent_task(
            method="analyze",
            parameters={
                "content": "Python is a high-level programming language known for its simplicity.",
                "question": "What makes Python popular for beginners?"
            }
        )
        
        print(f"\n🔍 Analysis completed:")
        if analysis_result.get('analysis'):
            print(f"   {analysis_result['analysis'][:400]}...")
        
        # Get final status
        print("\n" + "-"*40)
        print("FINAL STATUS")
        print("-"*40)
        
        status = await agent_hub.get_agent_status()
        print(f"\n📊 Agent Hub Status:")
        print(f"   - Total agents: {status['total_agents']}/{status['max_agents']}")
        print(f"   - Agents created:")
        
        for agent in status["agents"]:
            print(f"      • {agent['type']} agent ({agent['id']})")
            print(f"        - Requests: {agent['metrics']['total_requests']}")
            print(f"        - Sessions: {agent['sessions']}")
            print(f"        - Tools: {', '.join(agent['tools'])}")
        
        print("\n✅ All tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        logger.error(f"Test failed", exc_info=True)
        return False
        
    finally:
        # Cleanup
        logger.info("Cleaning up...")
        if agent_hub:
            await agent_hub.stop()
        if resource_manager:
            await resource_manager.stop()


async def main():
    """Main test runner"""
    print("\n⚠️  Prerequisites:")
    print("   • Ollama must be running (ollama serve)")
    print("   • llama3.2 model should be available")
    print("   • This will make real LLM calls")
    
    print("\nPress Enter to continue or Ctrl+C to cancel...")
    try:
        input()
    except KeyboardInterrupt:
        print("\nCancelled")
        return
    
    success = await test_real_agent_workflow()
    
    if success:
        print("\n🎉 Real agent workflow test passed!")
        sys.exit(0)
    else:
        print("\n💔 Real agent workflow test failed!")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)