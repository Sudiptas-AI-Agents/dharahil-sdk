"""Typed context envelope for DharaHIL tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DisplayHints:
    """Rendering hints for how to display tool call data in approval UIs."""

    title: str = ""
    category: str = ""
    sections: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "category": self.category,
            "sections": self.sections,
        }


@dataclass
class ToolContext:
    """Structured context for a tool call sent to DharaHIL."""

    agent_id: str
    run_id: str
    step_id: str = "step"
    risk_level: str = "MEDIUM"
    tags: list[str] = field(default_factory=list)
    context_summary: str = ""
    idempotency_key: str = ""
    decision_url: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    display: DisplayHints | None = None

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "risk_level": self.risk_level,
            "tags": self.tags,
            "context_summary": self.context_summary,
            "idempotency_key": self.idempotency_key,
            "decision_url": self.decision_url,
            "metadata": self.metadata,
            "display": self.display.to_dict() if self.display else None,
        }
