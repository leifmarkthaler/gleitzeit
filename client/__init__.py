"""
Socket.IO client components for Gleitzeit V4
"""

from client.socketio_provider import (
    SocketIOProviderClient, 
    SocketIOEchoProvider,
    SocketIOWebSearchProvider, 
    SocketIOTextProcessingProvider,
    SocketIOOllamaProvider,
    run_echo_provider,
    run_web_search_provider,
    run_text_processing_provider,
    run_ollama_provider
)

from client.socketio_engine import (
    SocketIOEngineClient,
    run_workflow_engine
)

__all__ = [
    "SocketIOProviderClient",
    "SocketIOEchoProvider", 
    "SocketIOWebSearchProvider",
    "SocketIOTextProcessingProvider",
    "SocketIOOllamaProvider",
    "run_echo_provider",
    "run_web_search_provider", 
    "run_text_processing_provider",
    "run_ollama_provider",
    "SocketIOEngineClient",
    "run_workflow_engine"
]