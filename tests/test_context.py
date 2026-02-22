"""Tests for ToolContext and DisplayHints dataclasses."""
from dharahil.context import DisplayHints, ToolContext


def test_tool_context_defaults():
    ctx = ToolContext(agent_id="bot", run_id="r1")
    assert ctx.agent_id == "bot"
    assert ctx.run_id == "r1"
    assert ctx.step_id == "step"
    assert ctx.risk_level == "MEDIUM"
    assert ctx.tags == []
    assert ctx.context_summary == ""
    assert ctx.metadata == {}
    assert ctx.display is None


def test_tool_context_to_dict():
    ctx = ToolContext(
        agent_id="bot",
        run_id="r1",
        metadata={"workspace": "acme"},
        display=DisplayHints(title="Send email", category="communication"),
    )
    d = ctx.to_dict()
    assert d["agent_id"] == "bot"
    assert d["metadata"] == {"workspace": "acme"}
    assert d["display"]["title"] == "Send email"
    assert d["display"]["category"] == "communication"


def test_tool_context_to_dict_no_display():
    ctx = ToolContext(agent_id="bot", run_id="r1")
    d = ctx.to_dict()
    assert d["display"] is None


def test_display_hints_defaults():
    dh = DisplayHints()
    assert dh.title == ""
    assert dh.category == ""
    assert dh.sections == []


def test_display_hints_to_dict():
    dh = DisplayHints(
        title="Post in #sales",
        category="communication",
        sections=[{"label": "Dest", "fields": [{"key": "channel", "label": "Channel"}]}],
    )
    d = dh.to_dict()
    assert d["title"] == "Post in #sales"
    assert len(d["sections"]) == 1
    assert d["sections"][0]["label"] == "Dest"
