"""
BaseAgent — shared scaffolding for all supply chain agents.

Every concrete agent (Procurement, Inventory, Budget) inherits from
this class. The pattern is intentionally simple: each agent exposes a
handle() method that processes an incoming Task and returns it with a
result attached.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from protocol.a2a import A2ABus, AgentCard, MessageRole, Task

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    def __init__(self, card: AgentCard, bus: A2ABus):
        self.card = card
        self.bus = bus
        self._registered = False

    def register(self):
        """Register this agent on the bus so other agents can reach it."""
        self.bus.register(self.card.name, self.handle)
        self._registered = True
        logger.info(f"[{self.card.name}] registered on bus")

    def send(
        self,
        recipient: str,
        action: str,
        payload: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> Task:
        """Create and dispatch a new task to another agent."""
        task = Task(
            sender=self.card.name,
            recipient=recipient,
            action=action,
            payload=payload,
        )
        if task_id:
            task.task_id = task_id

        task.add_message(
            MessageRole.AGENT,
            f"{self.card.name} → {recipient}: {action}",
            payload=payload,
        )
        logger.debug(f"[{self.card.name}] dispatching '{action}' to {recipient}")
        return self.bus.dispatch(task)

    @abstractmethod
    def handle(self, task: Task) -> Task:
        """Process an incoming task. Must be implemented by each agent."""
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.card.name}>"

# route() dispatches incoming task to handle_<action> method by convention

# route() dispatches incoming task to handle_<action> method by convention
