#!/bin/bash

# Gleitzeit UI Startup Script

echo "🚀 Starting Gleitzeit Web UI..."
echo ""

# Check if we're in the right directory
if [ ! -f "api/app.py" ]; then
    echo "❌ Error: Please run this script from the src/ui directory"
    exit 1
fi

# Install minimal dependencies if needed
echo "📦 Checking dependencies..."
python -c "import fastapi" 2>/dev/null || {
    echo "Installing FastAPI..."
    pip install fastapi uvicorn jinja2 python-multipart websockets
}

# Find an available port
PORT=8001
while lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; do
    echo "Port $PORT is in use, trying next port..."
    PORT=$((PORT + 1))
done

echo ""
echo "✅ Starting server on port $PORT"
echo "📍 Open your browser to: http://localhost:$PORT"
echo ""
echo "Press Ctrl+C to stop the server"
echo "================================"
echo ""

# Start the server
python -m uvicorn api.app:app --reload --port $PORT