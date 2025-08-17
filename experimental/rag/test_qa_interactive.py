#!/usr/bin/env python3
"""Interactive Q&A session for testing the RAG system."""

import asyncio
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent))

from test_qa_system import QASystem


async def main():
    """Run interactive Q&A session."""
    print("="*60)
    print("Interactive Q&A System")
    print("="*60)
    
    # Initialize Q&A system
    qa = QASystem(redis_port=6380)
    
    if not await qa.initialize():
        print("❌ Failed to initialize Q&A system")
        return 1
    
    # Check knowledge base
    info = qa.redis_client.ft(qa.index_name).info()
    existing_docs = info['num_docs']
    
    if existing_docs > 0:
        print(f"✅ Using existing knowledge base with {existing_docs} chunks")
    else:
        print("❌ No knowledge base found. Run test_qa_system.py first to load data.")
        await qa.cleanup()
        return 1
    
    # Run interactive session
    await qa.interactive_qa()
    
    # Cleanup
    await qa.cleanup()
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)