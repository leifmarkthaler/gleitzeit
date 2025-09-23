"""
Protocol Registry for Easy Client.

Automatically discovers registered protocols from the system and validates
protocol/method combinations.
"""

import redis
from typing import Dict, Set, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ProtocolRegistry:
    """
    Registry of available protocols and their methods.

    Loads from Redis to discover what's actually available in the system.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """Initialize protocol registry."""
        self.redis_url = redis_url
        self._protocols: Dict[str, Set[str]] = {}
        self._handlers: Dict[str, Dict[str, any]] = {}
        self._loaded = False

    def load_from_redis(self):
        """Load registered protocols from Redis."""
        try:
            r = redis.from_url(self.redis_url, decode_responses=True)

            # Get all registered handlers
            handlers = r.smembers('handlers:registered')

            for handler_id in handlers:
                handler_info = r.hgetall(f'handler:{handler_id}')

                if not handler_info:
                    continue

                protocol = handler_info.get('protocol', '')
                method = handler_info.get('method', '')

                if protocol and method:
                    if protocol not in self._protocols:
                        self._protocols[protocol] = set()
                    self._protocols[protocol].add(method)

                    # Store full handler info
                    key = f"{protocol}:{method}"
                    self._handlers[key] = handler_info

            self._loaded = True
            logger.info(f"Loaded {len(self._protocols)} protocols with {sum(len(m) for m in self._protocols.values())} methods")

        except Exception as e:
            logger.warning(f"Could not load protocols from Redis: {e}")
            self._load_defaults()

    def _load_defaults(self):
        """Load default protocols if Redis is not available."""
        self._protocols = {
            'python/v1': {'python/execute', 'python/eval'},
            'shell/v1': {'shell/execute', 'shell/run'},
            'http/v1': {'http/get', 'http/post', 'http/put', 'http/delete'},
            'timer/v1': {'timer/wait', 'timer/schedule'},
            'ollama/v1': {'ollama/generate', 'ollama/chat', 'ollama/embeddings'},
            'openai/v1': {'openai/chat', 'openai/completion'},
            'sql/v1': {'sql/query', 'sql/execute'},
            'redis/v1': {'redis/get', 'redis/set', 'redis/publish'},
            'filesystem/v1': {'filesystem/read', 'filesystem/write', 'filesystem/list'}
        }
        self._loaded = True
        logger.info("Loaded default protocol definitions")

    def ensure_loaded(self):
        """Ensure protocols are loaded."""
        if not self._loaded:
            self.load_from_redis()

    def get_protocols(self) -> Dict[str, Set[str]]:
        """Get all registered protocols and their methods."""
        self.ensure_loaded()
        return self._protocols.copy()

    def get_methods(self, protocol: str) -> Set[str]:
        """Get methods for a specific protocol."""
        self.ensure_loaded()
        return self._protocols.get(protocol, set()).copy()

    def validate_protocol_method(self, protocol: str, method: str) -> bool:
        """
        Validate if a protocol/method combination exists.

        Args:
            protocol: Protocol identifier (e.g., 'python/v1')
            method: Method name (e.g., 'python/execute')

        Returns:
            True if valid combination
        """
        self.ensure_loaded()
        return protocol in self._protocols and method in self._protocols[protocol]

    def parse_protocol_method(self, protocol_method: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse protocol/method string into components.

        Handles various formats:
        - "python/v1:execute" -> ("python/v1", "python/execute")
        - "ollama/v1:chat" -> ("ollama/v1", "ollama/chat")
        - "python" -> ("python/v1", "python/execute")  # defaults

        Args:
            protocol_method: Combined protocol/method string

        Returns:
            Tuple of (protocol, method) or (None, None) if invalid
        """
        self.ensure_loaded()

        # Handle empty/None
        if not protocol_method:
            return "python/v1", "python/execute"  # Default

        # Simple protocol name (e.g., "python")
        if '/' not in protocol_method and ':' not in protocol_method:
            # Try to find matching protocol
            for proto in self._protocols:
                if proto.startswith(protocol_method + '/'):
                    # Found protocol, use default method
                    methods = list(self._protocols[proto])
                    if methods:
                        return proto, methods[0]

        # Format: "protocol/version:method"
        if ':' in protocol_method:
            parts = protocol_method.split(':', 1)
            protocol = parts[0]
            method_part = parts[1]

            # Add version if missing
            if '/' not in protocol:
                protocol = f"{protocol}/v1"

            # Build full method name
            if '/' not in method_part:
                # Just method name, need to add protocol prefix
                method_prefix = protocol.split('/')[0]
                method = f"{method_prefix}/{method_part}"
            else:
                method = method_part

            # Validate
            if self.validate_protocol_method(protocol, method):
                return protocol, method
            else:
                # Try without the version
                base_protocol = protocol.split('/')[0]
                for proto in self._protocols:
                    if proto.startswith(base_protocol + '/'):
                        if method in self._protocols[proto]:
                            return proto, method

        return None, None

    def suggest_methods(self, protocol: str) -> str:
        """Get suggestion text for available methods."""
        self.ensure_loaded()

        methods = self.get_methods(protocol)
        if methods:
            return f"Available methods for {protocol}: {', '.join(sorted(methods))}"

        # Try to find similar protocol
        base = protocol.split('/')[0] if '/' in protocol else protocol
        for proto in self._protocols:
            if proto.startswith(base):
                methods = self._protocols[proto]
                return f"Did you mean {proto}? Available methods: {', '.join(sorted(methods))}"

        return f"Protocol {protocol} not found. Available protocols: {', '.join(sorted(self._protocols.keys()))}"


# Global registry instance
_registry = None

def get_registry() -> ProtocolRegistry:
    """Get or create the global protocol registry."""
    global _registry
    if _registry is None:
        _registry = ProtocolRegistry()
    return _registry