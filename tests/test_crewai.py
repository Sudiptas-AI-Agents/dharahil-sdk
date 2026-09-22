import asyncio
from unittest.mock import AsyncMock

from dharahil.client import DharaHILClient
from dharahil.crewai import require_approval


class FakeTool:
    name = "send_email"

    def __init__(self):
        self.calls = []

    def _run(self, **kwargs):
        self.calls.append(kwargs)
        return "sent"


def _client(outcome):
    c = DharaHILClient(base_url="http://t", api_key="k", tenant_id="t", app_id="a", environment="dev")
    c.run_approval_loop = AsyncMock(return_value=outcome)
    return c


def test_runs_with_approved_args():
    tool = require_approval(
        FakeTool(),
        dhara_client=_client({"action": "APPROVED", "tool_args": {"to": "edited@x.com"}}),
        context={"agent_id": "a", "run_id": "r", "risk_level": "HIGH"},
    )
    assert tool._run(to="orig@x.com") == "sent"
    assert tool.calls == [{"to": "edited@x.com"}]


def test_rejection_returns_readable_message():
    tool = require_approval(
        FakeTool(),
        dhara_client=_client({"action": "REJECTED", "note": "wrong customer"}),
        context=lambda args: {"agent_id": "a", "run_id": "r", "context_summary": f"email {args['to']}"},
    )
    assert tool._run(to="x@y.z") == "Not executed: a human reviewer rejected send_email: wrong customer"
    assert tool.calls == []


def test_works_inside_running_loop():
    tool = require_approval(
        FakeTool(),
        dhara_client=_client({"action": "ALLOW", "tool_args": {"to": "x"}}),
        context={"agent_id": "a", "run_id": "r"},
    )

    async def inside():
        return tool._run(to="x")

    assert asyncio.run(inside()) == "sent"
