"""
Log System Core Components

Provides centralized logging infrastructure for Gleitzeit including:
- Structured log data models
- Log collection and buffering
- Real-time streaming support
- Persistent storage integration
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class LogLevel(str, Enum):
    """Log severity levels"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogSource(str, Enum):
    """Log source types"""
    PROVIDER = "provider"
    ENGINE = "engine"
    QUEUE = "queue"
    DOCKER = "docker"
    SYSTEM = "system"
    SCHEDULER = "scheduler"
    RETRY = "retry"
    DEPENDENCY = "dependency"
    HUB = "hub"
    API = "api"


@dataclass
class LogEntry:
    """Single log entry with full context"""
    timestamp: datetime
    level: LogLevel
    message: str
    source: LogSource
    
    # Context
    task_id: Optional[str] = None
    workflow_id: Optional[str] = None
    provider_id: Optional[str] = None
    
    # Additional data
    stream_type: Optional[str] = None  # stdout, stderr, http
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level.value if isinstance(self.level, LogLevel) else self.level,
            "message": self.message,
            "source": self.source.value if isinstance(self.source, LogSource) else self.source,
            "task_id": self.task_id,
            "workflow_id": self.workflow_id,
            "provider_id": self.provider_id,
            "stream_type": self.stream_type,
            "line_number": self.line_number,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogEntry':
        """Create from dictionary"""
        # Convert timestamp string to datetime
        timestamp = data.get('timestamp')
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif not isinstance(timestamp, datetime):
            timestamp = datetime.utcnow()
        
        # Convert level and source to enums
        level = data.get('level', 'info')
        if not isinstance(level, LogLevel):
            level = LogLevel(level) if level in [l.value for l in LogLevel] else LogLevel.INFO
        
        source = data.get('source', 'system')
        if not isinstance(source, LogSource):
            source = LogSource(source) if source in [s.value for s in LogSource] else LogSource.SYSTEM
        
        return cls(
            timestamp=timestamp,
            level=level,
            message=data.get('message', ''),
            source=source,
            task_id=data.get('task_id'),
            workflow_id=data.get('workflow_id'),
            provider_id=data.get('provider_id'),
            stream_type=data.get('stream_type'),
            line_number=data.get('line_number'),
            metadata=data.get('metadata', {})
        )


@dataclass
class LogStats:
    """Aggregated log statistics"""
    total_logs: int = 0
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    debug_count: int = 0
    sources: Dict[str, int] = field(default_factory=dict)
    first_log_at: Optional[datetime] = None
    last_log_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "total_logs": self.total_logs,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "debug_count": self.debug_count,
            "sources": self.sources,
            "first_log_at": self.first_log_at.isoformat() if self.first_log_at else None,
            "last_log_at": self.last_log_at.isoformat() if self.last_log_at else None
        }


@dataclass
class LogEventData:
    """Event data for log events"""
    entry: LogEntry
    batch: Optional[List[LogEntry]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to event data dictionary"""
        data = self.entry.to_dict()
        if self.batch:
            data["batch"] = [entry.to_dict() for entry in self.batch]
        return data