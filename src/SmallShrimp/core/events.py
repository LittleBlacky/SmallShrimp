from __future__ import annotations
from dataclasses import dataclass, field
import time

@dataclass
class Event:
    session_id: str
    content: str
    timestamp: float = field(default_factory=time.time)

@dataclass
class InboundEvent(Event):
    retry_count: int = 0
    
@dataclass
class OutboundEvent(Event):
    error: str | None = None