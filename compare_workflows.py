#!/usr/bin/env python3
"""
Compare Multi-Task LLM vs Agent Workflows
Demonstrates the key differences in approach and complexity.
"""

import asyncio
import time
from gleitzeit import GleitzeitClient

async def run_comparison():
    """Run both workflows and compare results"""
    
    print("🔍 WORKFLOW COMPARISON DEMO")
    print("=" * 50)
    
    async with GleitzeitClient() as client:
        
        print("\n📋 MULTI-TASK LLM WORKFLOW")
        print("-" * 30)
        print("✓ 10 manually defined tasks")
        print("✓ Explicit dependencies between each step") 
        print("✓ Full control over every LLM interaction")
        print("✓ Manual coordination of research → code → docs")
        print("✓ Static workflow structure")
        
        start_time = time.time()
        
        try:
            # Run multi-task LLM workflow
            print("\n🚀 Executing Multi-Task LLM Workflow...")
            llm_results = await client.run_workflow("multi_task_llm_example.yaml")
            llm_duration = time.time() - start_time
            
            print(f"✅ Completed in {llm_duration:.1f}s")
            print(f"📊 Tasks executed: {len(llm_results)}")
            
            # Show task breakdown
            for task_id, result in llm_results.items():
                status = "✅" if result.get('status') == 'completed' else "❌"
                print(f"  {status} {task_id}")
                
        except Exception as e:
            print(f"❌ Multi-task workflow failed: {e}")
            llm_results = {}
            llm_duration = 0
        
        print("\n" + "=" * 50)
        
        print("\n🤖 AGENT WORKFLOW")
        print("-" * 20)
        print("✓ 5 high-level agent tasks")
        print("✓ Autonomous planning and execution")
        print("✓ Session memory across interactions")
        print("✓ Self-correction and tool orchestration")
        print("✓ Dynamic workflow adaptation")
        
        start_time = time.time()
        
        try:
            # Run agent workflow
            print("\n🚀 Executing Agent Workflow...")
            agent_results = await client.run_workflow("agent_workflow_example.yaml")
            agent_duration = time.time() - start_time
            
            print(f"✅ Completed in {agent_duration:.1f}s")
            print(f"📊 Agent tasks: {len(agent_results)}")
            
            # Show agent task results
            for task_id, result in agent_results.items():
                status = "✅" if result.get('status') == 'completed' else "❌"
                print(f"  {status} {task_id}")
                
                # Show agent internal steps for research task
                if task_id == "comprehensive_research" and result.get('result'):
                    steps = result['result'].get('steps_executed', 0)
                    print(f"    └─ Internal steps executed: {steps}")
                    
        except Exception as e:
            print(f"❌ Agent workflow failed: {e}")
            agent_results = {}
            agent_duration = 0
        
        # Comparison summary
        print("\n" + "=" * 50)
        print("📈 COMPARISON SUMMARY")
        print("-" * 20)
        
        print(f"Multi-Task LLM Workflow:")
        print(f"  • Workflow Definition: 95 lines of YAML")
        print(f"  • Manual Tasks: 10")
        print(f"  • Execution Time: {llm_duration:.1f}s")
        print(f"  • Control Level: Maximum")
        print(f"  • Planning: Manual (developer)")
        
        print(f"\nAgent Workflow:")
        print(f"  • Workflow Definition: 45 lines of YAML")
        print(f"  • Agent Tasks: 5")
        print(f"  • Execution Time: {agent_duration:.1f}s")
        print(f"  • Control Level: High-level goals")
        print(f"  • Planning: Autonomous (agent)")
        
        print(f"\n🎯 KEY DIFFERENCES:")
        print(f"  • Complexity Reduction: {((95-45)/95)*100:.0f}% fewer lines")
        print(f"  • Task Reduction: {((10-5)/10)*100:.0f}% fewer tasks to define")
        print(f"  • Agent handles internal orchestration automatically")
        print(f"  • Session memory enables conversational refinement")
        print(f"  • Self-correction reduces manual error handling")
        
        # Quality comparison (if both succeeded)
        if llm_results and agent_results:
            print(f"\n📝 OUTPUT QUALITY:")
            print(f"  • Both approaches produce comprehensive results")
            print(f"  • Multi-task: More deterministic, predictable")
            print(f"  • Agent: More adaptive, context-aware")
            print(f"  • Agent maintains conversation context for refinement")

if __name__ == "__main__":
    asyncio.run(run_comparison())