"""
Run the Gleitzeit UI server
"""

import os
import sys
import logging

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Run UI server"""
    import uvicorn
    from gleitzeit.ui.api.app import app

    port = int(os.getenv("GLEITZEIT_UI_PORT", "8004"))
    host = os.getenv("GLEITZEIT_UI_HOST", "0.0.0.0")

    print(f"Starting Gleitzeit UI on http://{host}:{port}")
    print(f"API Server expected at: {os.getenv('GLEITZEIT_API_URL', 'http://localhost:8000')}")
    print("\nOpen your browser to http://localhost:8004")

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()