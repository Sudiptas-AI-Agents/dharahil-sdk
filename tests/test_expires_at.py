"""Tests for expires_at propagation through InterceptorResult, before_execute, and wait_for_decision."""
import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dharahil.client import DharaHILClient
from dharahil.interceptor import InterceptorAction, InterceptorResult


@pytest.fixture
def client():
    return DharaHILClient(
        base_url="http://test:4990",
        api_key="test-key",
        tenant_id="tid",
        app_id="aid",
        environment="dev",
    )


def _mock_response(status_code=200, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


# --- InterceptorResult dataclass ---

def test_interceptor_result_expires_at_default():
    """InterceptorResult defaults expires_at to None."""
    r = InterceptorResult(action=InterceptorAction.ALLOW)
    assert r.expires_at is None


def test_interceptor_result_expires_at_set():
    """InterceptorResult stores expires_at when provided."""
    r = InterceptorResult(
        action=InterceptorAction.REQUIRE_APPROVAL,
        request_id="req-1",
        expires_at="2026-02-22T12:00:00Z",
    )
    assert r.expires_at == "2026-02-22T12:00:00Z"


# --- before_execute returns expires_at ---

@pytest.mark.asyncio
async def test_before_execute_passes_expires_at(client):
    """REQUIRE_APPROVAL response includes expires_at in the InterceptorResult."""
    gateway_response = {
        "request_id": "req-abc",
        "expires_at": "2026-02-22T15:30:00Z",
    }
    with patch("dharahil.client.httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post.return_value = _mock_response(200, gateway_response)
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst

        result = await client.before_execute(
            "send_email",
            {"to": "bob@example.com"},
            {"agent_id": "bot", "run_id": "r1"},
        )

    assert result.action == InterceptorAction.REQUIRE_APPROVAL
    assert result.request_id == "req-abc"
    assert result.expires_at == "2026-02-22T15:30:00Z"


@pytest.mark.asyncio
async def test_before_execute_allow_no_expires_at(client):
    """ALLOW response has no expires_at (not needed)."""
    with patch("dharahil.client.httpx.AsyncClient") as mock_cls:
        mock_inst = AsyncMock()
        mock_inst.post.return_value = _mock_response(200, {"action": "ALLOW", "request_id": None})
        mock_inst.__aenter__ = AsyncMock(return_value=mock_inst)
        mock_inst.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_inst

        result = await client.before_execute(
            "read_file", {"path": "/tmp/x"}, {"agent_id": "bot", "run_id": "r1"},
        )

    assert result.action == InterceptorAction.ALLOW
    assert result.expires_at is None


# --- wait_for_decision timeout behavior ---

@pytest.mark.asyncio
async def test_wait_for_decision_uses_expires_at(client):
    """When expires_at is provided, wait_for_decision computes timeout from it."""
    # Decision returned on first poll
    decided = {
        "request_id": "req-1",
        "status": "APPROVED",
        "last_decision": "approve",
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=decided):
        expires = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
        result = await client.wait_for_decision("req-1", expires_at=expires)

    assert result["last_decision"] == "approve"


@pytest.mark.asyncio
async def test_wait_for_decision_explicit_timeout_overrides_expires_at(client):
    """Explicit timeout_seconds takes priority over expires_at."""
    decided = {
        "request_id": "req-2",
        "status": "APPROVED",
        "last_decision": "approve",
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=decided):
        # expires_at is far in the future but explicit timeout is short
        far_future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        result = await client.wait_for_decision(
            "req-2", timeout_seconds=5, expires_at=far_future,
        )

    assert result["last_decision"] == "approve"


@pytest.mark.asyncio
async def test_wait_for_decision_expired_expires_at_uses_minimum(client):
    """If expires_at is in the past, effective timeout clamps to minimum 10s."""
    decided = {
        "request_id": "req-3",
        "status": "APPROVED",
        "last_decision": "approve",
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=decided):
        past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        result = await client.wait_for_decision("req-3", expires_at=past)

    assert result["last_decision"] == "approve"


@pytest.mark.asyncio
async def test_wait_for_decision_invalid_expires_at_falls_back(client):
    """Unparseable expires_at falls back to 600s default."""
    decided = {
        "request_id": "req-4",
        "status": "APPROVED",
        "last_decision": "approve",
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=decided):
        result = await client.wait_for_decision("req-4", expires_at="not-a-date")

    assert result["last_decision"] == "approve"


@pytest.mark.asyncio
async def test_wait_for_decision_stops_on_non_pending_status(client):
    """Exits early when status is neither PENDING nor REVISE_REQUESTED."""
    expired_req = {
        "request_id": "req-5",
        "status": "EXPIRED",
        "last_decision": None,
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=expired_req):
        result = await client.wait_for_decision("req-5", timeout_seconds=30)

    assert result["status"] == "EXPIRED"
    assert result["last_decision"] is None


@pytest.mark.asyncio
async def test_wait_for_decision_timeout_raises(client):
    """TimeoutError raised when no decision within timeout."""
    pending = {
        "request_id": "req-6",
        "status": "PENDING",
        "last_decision": None,
    }
    with patch.object(client, "get_request", new_callable=AsyncMock, return_value=pending):
        with pytest.raises(TimeoutError, match="No decision for request req-6"):
            await client.wait_for_decision(
                "req-6", timeout_seconds=1, poll_interval_seconds=0.3,
            )
