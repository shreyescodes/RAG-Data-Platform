from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime


class BaseAgent(ABC):
    def __init__(self, name: str):
        self.name = name
        self.reasoning_log = []

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent's primary function"""
        pass

    def log_reasoning(self, step: str, details: Any):
        """Log agent reasoning for explainability"""
        self.reasoning_log.append({
            "agent": self.name,
            "step": step,
            "details": details,
            "timestamp": datetime.utcnow().isoformat()
        })

    def get_reasoning(self) -> list:
        """Get all reasoning steps"""
        return self.reasoning_log

    def clear_reasoning(self):
        """Clear reasoning log"""
        self.reasoning_log = []
