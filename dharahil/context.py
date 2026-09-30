"""Typed context envelope for DharaHIL tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DisplayHints:
    """Rendering hints for how to display tool call data in approval UIs.

    `choices` ([{id, label}], max 4) turns the single Approve into one Approve per option; the
    picked id comes back as `last_decision_choice` from get_request()."""

    title: str = ""
    category: str = ""
    sections: list[dict] = field(default_factory=list)
    choices: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "category": self.category,
            "sections": self.sections,
        }
        if self.choices:
            d["choices"] = self.choices
        return d


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
