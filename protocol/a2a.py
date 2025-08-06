"""
Lightweight simulation of Google's Agent2Agent (A2A) protocol.

This module models the core concepts from A2A:
  - AgentCard  : describes what an agent can do
  - Message    : a single communication unit
  - Task       : a unit of work with a lifecycle
  - A2ABus     : in-process message bus (replaces HTTP in prod)

In a production setup you'd replace A2ABus with actual A2A HTTP
endpoints, but the agent logic stays identical.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class TaskState(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    FAILED      = "failed"
    BLOCKED     = "blocked"   # governance layer stopped it


class MessageRole(str, Enum):
    USER  = "user"
    AGENT = "agent"


@dataclass
class AgentCard:
    """Public descriptor for an agent — what it does and how to reach it."""
    name: str
    description: str
    version: str = "1.0.0"
    skills: List[str] = field(default_factory=list)
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "skills": self.skills,
        }


@dataclass
class Message:
    role: MessageRole
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "role": self.role.value,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Task:
    """
    A unit of work passed between agents.

    The lifecycle is:  PENDING → IN_PROGRESS → COMPLETED
                                             → FAILED
                                             → BLOCKED  (governance)
    """
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sender: str = ""
    recipient: str = ""
    action: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    messages: List[Message] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_message(self, role: MessageRole, content: str, **meta):
        self.messages.append(Message(role=role, content=content, metadata=meta))
        self.updated_at = datetime.utcnow()

    def complete(self, result: Dict[str, Any]):
        self.state = TaskState.COMPLETED
        self.result = result
        self.updated_at = datetime.utcnow()

    def fail(self, reason: str):
        self.state = TaskState.FAILED
        self.result = {"error": reason}
        self.updated_at = datetime.utcnow()

    def block(self, reason: str):
        self.state = TaskState.BLOCKED
        self.result = {"blocked_reason": reason}
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "sender": self.sender,
            "recipient": self.recipient,
            "action": self.action,
            "payload": self.payload,
            "state": self.state.value,
            "result": self.result,
            "messages": [m.to_dict() for m in self.messages],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# Type alias for agent handler functions
AgentHandler = Callable[[Task], Task]


class A2ABus:
    """
    In-process message bus that routes tasks between agents.

    Each agent registers a handler under its name. When a task
    is dispatched, the bus finds the right handler and calls it —
    but only after the governance interceptor has had a look.
    """

    def __init__(self):
        self._handlers: Dict[str, AgentHandler] = {}
        self._interceptor: Optional[Callable] = None

    def register(self, agent_name: str, handler: AgentHandler):
        self._handlers[agent_name] = handler

    def set_interceptor(self, interceptor: Callable):
        """
        The governance interceptor. It receives the task before the
        recipient agent does, and can block or modify it.
        """
        self._interceptor = interceptor

    def dispatch(self, task: Task) -> Task:
        if self._interceptor:
            task = self._interceptor(task)
            # if governance blocked it, don't deliver
            if task.state == TaskState.BLOCKED:
                return task

        handler = self._handlers.get(task.recipient)
        if not handler:
            task.fail(f"No agent registered with name '{task.recipient}'")
            return task

        task.state = TaskState.IN_PROGRESS
        return handler(task)

# interceptor hook: set_interceptor registers governance callback on bus dispatch

# interceptor hook: set_interceptor registers governance callback on bus dispatch
