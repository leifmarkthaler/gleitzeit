#!/usr/bin/env python3
"""
Run the Gleitzeit API server
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if __name__ == "__main__":
    import uvicorn
    from gleitzeit.api.main import app
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )