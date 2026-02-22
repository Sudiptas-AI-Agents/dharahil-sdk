"""Tests for LangGraph adapter: approval, rejection, and revision flows."""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock langgraph before importing the adapter
mock_langgraph = MagicMock()
mock_interrupt = AsyncMock()
mock_langgraph.graph.interrupt = mock_interrupt
sys.modules["langgraph"] = mock_langgraph
sys.modules["langgraph.graph"] = mock_langgraph.graph

from dharahil.client import DharaHILClient
from dharahil.interceptor import InterceptorAction, InterceptorResult
from dharahil.langgraph_adapter import wrap_tool_with_dharahil


@pytest.fixture
def client():
    return DharaHILClient(
        base_url="http://test:4990",
        api_key="test-key",
        tenant_id="tid",
        app_id="aid",
        environment="dev",
    )


@pytest.fixture(autouse=True)
def reset_interrupt():
    """Reset the shared mock_interrupt before each test."""
    mock_interrupt.reset_mock()
    mock_interrupt.side_effect = None
    mock_interrupt.return_value = None


def _allow_result():
    return InterceptorResult(action=InterceptorAction.ALLOW)


def _deny_result():
    return InterceptorResult(action=InterceptorAction.DENY, reason="policy denied")


def _require_approval_result(request_id="req-1"):
    return InterceptorResult(
        action=InterceptorAction.REQUIRE_APPROVAL,
        request_id=request_id,
        expires_at="2026-02-22T15:00:00Z",
    )


@pytest.mark.asyncio
async def test_allow_executes_immediately(client):
    """When policy ALLOWs, tool runs without interrupt."""
    tool = AsyncMock(return_value="sent")
    client.before_execute = AsyncMock(return_value=_allow_result())

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="bob@example.com")

    assert result == "sent"
    tool.assert_called_once()
    mock_interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_deny_raises_without_interrupt(client):
    """When policy DENYs, RuntimeError raised without interrupt."""
    tool = AsyncMock()
    client.before_execute = AsyncMock(return_value=_deny_result())

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    with pytest.raises(RuntimeError, match="denied"):
        await wrapped(to="bob@example.com")

    tool.assert_not_called()
    mock_interrupt.assert_not_called()


@pytest.mark.asyncio
async def test_approve_after_interrupt(client):
    """REQUIRE_APPROVAL → interrupt → approve → tool executes."""
    tool = AsyncMock(return_value="sent")
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    mock_interrupt.return_value = {"decision": "approve"}

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="bob@example.com")

    assert result == "sent"
    tool.assert_called_once()

    # Verify interrupt was called with correct payload
    pause_payload = mock_interrupt.call_args[0][0]
    assert pause_payload["request_id"] == "req-1"
    assert pause_payload["type"] == "approval_required"
    assert pause_payload["expires_at"] == "2026-02-22T15:00:00Z"


@pytest.mark.asyncio
async def test_reject_after_interrupt(client):
    """REQUIRE_APPROVAL → interrupt → reject → RuntimeError."""
    tool = AsyncMock()
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    mock_interrupt.return_value = {"decision": "reject", "note": "not appropriate"}

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    with pytest.raises(RuntimeError, match="rejected by human.*not appropriate"):
        await wrapped(to="bob@example.com")

    tool.assert_not_called()


@pytest.mark.asyncio
async def test_revise_with_updated_args_submits_proposal_and_re_interrupts(client):
    """Revise with updated_args → submit proposal → interrupt again → approve."""
    tool = AsyncMock(return_value="sent to alice")
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    client.submit_proposal_update = AsyncMock(return_value={
        "request_id": "req-1",
        "version": 2,
        "status": "PENDING",
    })

    call_count = 0

    async def interrupt_side_effect(payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "decision": "revise",
                "revise_input": "Send to alice instead",
                "updated_args": {"to": "alice@example.com"},
            }
        else:
            return {"decision": "approve"}

    mock_interrupt.side_effect = interrupt_side_effect

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="bob@example.com")

    assert result == "sent to alice"
    tool.assert_called_once()
    call_kwargs = tool.call_args[1]
    assert call_kwargs["to"] == "alice@example.com"

    # Proposal update was submitted
    client.submit_proposal_update.assert_called_once()
    update_call = client.submit_proposal_update.call_args
    assert update_call.args[0] == "req-1"
    assert update_call.kwargs["version_from"] == 1
    assert update_call.kwargs["updated_tool_args"]["to"] == "alice@example.com"

    assert call_count == 2


@pytest.mark.asyncio
async def test_revise_without_updated_args_sends_revision_instructions(client):
    """Revise without updated_args → interrupt with revision_requested → orchestrator provides args → approve."""
    tool = AsyncMock(return_value="sent to carol")
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    client.submit_proposal_update = AsyncMock(return_value={
        "request_id": "req-1",
        "version": 2,
        "status": "PENDING",
    })

    call_count = 0

    async def interrupt_side_effect(payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "decision": "revise",
                "revise_input": "Change recipient to carol",
            }
        elif call_count == 2:
            assert payload["type"] == "revision_requested"
            assert payload["revise_input"] == "Change recipient to carol"
            assert payload["current_args"]["to"] == "bob@example.com"
            return {
                "decision": "revise",
                "revise_input": "Change recipient to carol",
                "updated_args": {"to": "carol@example.com"},
            }
        else:
            assert payload["type"] == "revised_proposal_pending"
            return {"decision": "approve"}

    mock_interrupt.side_effect = interrupt_side_effect

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="bob@example.com")

    assert result == "sent to carol"
    assert call_count == 3
    client.submit_proposal_update.assert_called_once()


@pytest.mark.asyncio
async def test_revise_then_reject(client):
    """Revise → submit proposal → human rejects the revision."""
    tool = AsyncMock()
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    client.submit_proposal_update = AsyncMock(return_value={
        "request_id": "req-1",
        "version": 2,
        "status": "PENDING",
    })

    call_count = 0

    async def interrupt_side_effect(payload):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {
                "decision": "revise",
                "revise_input": "Try different params",
                "updated_args": {"to": "dave@example.com"},
            }
        else:
            return {"decision": "reject", "note": "Still not right"}

    mock_interrupt.side_effect = interrupt_side_effect

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    with pytest.raises(RuntimeError, match="rejected by human.*Still not right"):
        await wrapped(to="bob@example.com")

    tool.assert_not_called()
    assert call_count == 2


@pytest.mark.asyncio
async def test_revise_auto_allowed_by_policy(client):
    """Revised proposal auto-allowed by policy → tool executes without second interrupt."""
    tool = AsyncMock(return_value="auto-sent")
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    client.submit_proposal_update = AsyncMock(return_value={
        "request_id": "req-1",
        "version": 2,
        "status": "AUTO_ALLOWED",
    })
    mock_interrupt.return_value = {
        "decision": "revise",
        "revise_input": "Lower risk operation",
        "updated_args": {"to": "internal@company.com"},
    }

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="external@other.com")

    assert result == "auto-sent"
    tool.assert_called_once()
    client.submit_proposal_update.assert_called_once()
    # Only one interrupt call — auto-allowed after proposal update
    assert mock_interrupt.call_count == 1


@pytest.mark.asyncio
async def test_revise_auto_denied_by_policy(client):
    """Revised proposal auto-denied by policy → RuntimeError without second interrupt."""
    tool = AsyncMock()
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    client.submit_proposal_update = AsyncMock(return_value={
        "request_id": "req-1",
        "version": 2,
        "status": "AUTO_DENIED",
    })
    mock_interrupt.return_value = {
        "decision": "revise",
        "revise_input": "Higher risk operation",
        "updated_args": {"to": "admin@root.com"},
    }

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    with pytest.raises(RuntimeError, match="auto-denied"):
        await wrapped(to="user@example.com")

    tool.assert_not_called()
    assert mock_interrupt.call_count == 1


@pytest.mark.asyncio
async def test_approve_with_updated_args(client):
    """Approve with updated_args → tool runs with those args."""
    tool = AsyncMock(return_value="sent to override")
    client.before_execute = AsyncMock(return_value=_require_approval_result())
    mock_interrupt.return_value = {
        "decision": "approve",
        "updated_args": {"to": "override@example.com"},
    }

    wrapped = wrap_tool_with_dharahil(tool, dhara_client=client, tool_name="send_email")
    result = await wrapped(to="bob@example.com")

    assert result == "sent to override"
    call_kwargs = tool.call_args[1]
    assert call_kwargs["to"] == "override@example.com"
