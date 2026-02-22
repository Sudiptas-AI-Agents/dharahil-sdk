"""Tests for DharaHILClient.run_approval_loop() and wait_for_decision(after_version=)."""

import pytest
from unittest.mock import AsyncMock, patch

from dharahil.client import DharaHILClient
from dharahil.interceptor import InterceptorAction, InterceptorResult


def _make_client() -> DharaHILClient:
    return DharaHILClient(
        base_url="http://test",
        api_key="key",
        tenant_id="t1",
        app_id="a1",
        environment="test",
    )


# ── wait_for_decision with after_version ──


@pytest.mark.asyncio
async def test_wait_skips_stale_revise_decision():
    """After submitting version 2, a stale REVISE_REQUESTED with version=2 is skipped."""
    client = _make_client()
    call_count = 0

    async def mock_get_request(rid):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            # First 2 polls: stale revise from version 1
            return {
                "status": "REVISE_REQUESTED",
                "version": 2,
                "last_decision": "revise",
                "last_decision_revise_input": "old instructions",
            }
        # 3rd poll: new approve decision
        return {
            "status": "APPROVED",
            "version": 2,
            "last_decision": "approve",
            "last_decision_note": "looks good",
        }

    with patch.object(client, "get_request", side_effect=mock_get_request):
        result = await client.wait_for_decision(
            "req1",
            timeout_seconds=10,
            poll_interval_seconds=0.01,
            after_version=2,
        )

    assert result["last_decision"] == "approve"
    assert call_count == 3


@pytest.mark.asyncio
async def test_wait_returns_immediately_without_after_version():
    """Without after_version, returns the first decision seen."""
    client = _make_client()

    async def mock_get_request(rid):
        return {
            "status": "REVISE_REQUESTED",
            "version": 2,
            "last_decision": "revise",
            "last_decision_revise_input": "change it",
        }

    with patch.object(client, "get_request", side_effect=mock_get_request):
        result = await client.wait_for_decision(
            "req1",
            timeout_seconds=5,
            poll_interval_seconds=0.01,
        )

    assert result["last_decision"] == "revise"


# ── run_approval_loop ──


@pytest.mark.asyncio
async def test_loop_allow():
    """Policy ALLOW returns immediately without polling."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(action=InterceptorAction.ALLOW),
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"to": "a@b.com"},
            context={"agent_id": "ag1"},
        )

    assert result["action"] == "ALLOW"
    assert result["tool_args"]["to"] == "a@b.com"


@pytest.mark.asyncio
async def test_loop_deny():
    """Policy DENY returns immediately."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.DENY, reason="blocked"
        ),
    ):
        result = await client.run_approval_loop(
            tool_name="drop_table",
            tool_args={},
            context={},
        )

    assert result["action"] == "DENY"
    assert result["reason"] == "blocked"


@pytest.mark.asyncio
async def test_loop_approve():
    """Approval flow: REQUIRE_APPROVAL → poll → APPROVED."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
            expires_at="2099-01-01T00:00:00Z",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        return_value={
            "status": "APPROVED",
            "version": 1,
            "last_decision": "approve",
        },
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"to": "a@b.com"},
            context={},
        )

    assert result["action"] == "APPROVED"
    assert result["tool_args"]["to"] == "a@b.com"


@pytest.mark.asyncio
async def test_loop_reject():
    """Rejection flow."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        return_value={
            "status": "REJECTED",
            "version": 1,
            "last_decision": "reject",
            "last_decision_note": "not appropriate",
        },
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={},
            context={},
        )

    assert result["action"] == "REJECTED"
    assert result["note"] == "not appropriate"


@pytest.mark.asyncio
async def test_loop_revise_without_callback():
    """Revise without on_revise callback returns REVISE_REQUESTED to caller."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        return_value={
            "status": "REVISE_REQUESTED",
            "version": 1,
            "last_decision": "revise",
            "last_decision_revise_input": "add greeting",
        },
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"text": "hello"},
            context={},
        )

    assert result["action"] == "REVISE_REQUESTED"
    assert result["revise_input"] == "add greeting"
    assert result["current_args"]["text"] == "hello"


@pytest.mark.asyncio
async def test_loop_revise_with_callback_then_approve():
    """Revise with on_revise callback → submit proposal → poll → approve."""
    client = _make_client()

    async def on_revise(current_args, revise_input, revise_patch):
        return {"text": current_args["text"] + " - revised"}

    wait_call_count = 0

    async def mock_wait(rid, **kwargs):
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count == 1:
            return {
                "status": "REVISE_REQUESTED",
                "version": 1,
                "last_decision": "revise",
                "last_decision_revise_input": "add signature",
            }
        return {
            "status": "APPROVED",
            "version": 2,
            "last_decision": "approve",
        }

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        side_effect=mock_wait,
    ), patch.object(
        client,
        "submit_proposal_update",
        return_value={"version": 2, "status": "PENDING"},
    ) as mock_submit:
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"text": "hello"},
            context={"context_summary": "test", "risk_level": "LOW", "tags": []},
            on_revise=on_revise,
        )

    assert result["action"] == "APPROVED"
    assert result["tool_args"]["text"] == "hello - revised"
    mock_submit.assert_called_once()
    # Verify the updated args were passed to submit_proposal_update
    call_kwargs = mock_submit.call_args[1]
    assert call_kwargs["updated_tool_args"]["text"] == "hello - revised"


@pytest.mark.asyncio
async def test_loop_revise_auto_allowed_after_proposal():
    """After revise + proposal update, policy auto-allows."""
    client = _make_client()

    async def on_revise(current_args, revise_input, revise_patch):
        return {"text": "safe content"}

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        return_value={
            "status": "REVISE_REQUESTED",
            "version": 1,
            "last_decision": "revise",
            "last_decision_revise_input": "make it safer",
        },
    ), patch.object(
        client,
        "submit_proposal_update",
        return_value={"version": 2, "status": "AUTO_ALLOWED"},
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"text": "risky"},
            context={},
            on_revise=on_revise,
        )

    assert result["action"] == "AUTO_ALLOWED"
    assert result["tool_args"]["text"] == "safe content"


@pytest.mark.asyncio
async def test_loop_expired():
    """Request expires → returns EXPIRED."""
    client = _make_client()

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        return_value={
            "status": "EXPIRED",
            "version": 1,
            "last_decision": None,
        },
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={},
            context={},
        )

    assert result["action"] == "EXPIRED"


@pytest.mark.asyncio
async def test_loop_multiple_revisions():
    """Two revisions before final approval."""
    client = _make_client()

    revise_count = 0

    async def on_revise(current_args, revise_input, revise_patch):
        nonlocal revise_count
        revise_count += 1
        return {"text": f"revision-{revise_count}"}

    wait_call_count = 0

    async def mock_wait(rid, **kwargs):
        nonlocal wait_call_count
        wait_call_count += 1
        if wait_call_count <= 2:
            return {
                "status": "REVISE_REQUESTED",
                "version": wait_call_count,
                "last_decision": "revise",
                "last_decision_revise_input": f"change {wait_call_count}",
            }
        return {
            "status": "APPROVED",
            "version": 3,
            "last_decision": "approve",
        }

    submit_call_count = 0

    async def mock_submit(rid, **kwargs):
        nonlocal submit_call_count
        submit_call_count += 1
        return {"version": submit_call_count + 1, "status": "PENDING"}

    with patch.object(
        client,
        "before_execute",
        return_value=InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id="req1",
        ),
    ), patch.object(
        client,
        "wait_for_decision",
        side_effect=mock_wait,
    ), patch.object(
        client,
        "submit_proposal_update",
        side_effect=mock_submit,
    ):
        result = await client.run_approval_loop(
            tool_name="send_email",
            tool_args={"text": "original"},
            context={},
            on_revise=on_revise,
        )

    assert result["action"] == "APPROVED"
    assert result["tool_args"]["text"] == "revision-2"
    assert revise_count == 2
    assert submit_call_count == 2
