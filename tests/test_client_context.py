"""Test that DharaHILClient.before_execute accepts both dict and ToolContext."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dharahil.client import DharaHILClient
from dharahil.context import DisplayHints, ToolContext


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
    """Create a mock httpx.Response.

    httpx.Response.json() and raise_for_status() are synchronous methods,
    so we use MagicMock (not AsyncMock) for the response object.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {"action": "ALLOW", "request_id": None}
    return resp


@pytest.mark.asyncio
async def test_before_execute_with_dict(client):
    """Old dict-based context still works and includes metadata defaults."""
    with patch("dharahil.client.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.post.return_value = _mock_response()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value = mock_instance

        result = await client.before_execute(
            "send_email",
            {"to": "bob@example.com"},
            {"agent_id": "bot", "run_id": "r1", "risk_level": "HIGH"},
        )

        call_args = mock_instance.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["agent_id"] == "bot"
        assert payload["risk_level"] == "HIGH"
        assert payload["metadata"] == {}
        assert payload["display_hints"] is None


@pytest.mark.asyncio
async def test_before_execute_with_tool_context(client):
    """New ToolContext is accepted and metadata/display_hints are sent."""
    with patch("dharahil.client.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.post.return_value = _mock_response()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value = mock_instance

        ctx = ToolContext(
            agent_id="slack-bot",
            run_id="r2",
            metadata={"workspace": "acme"},
            display=DisplayHints(title="Post in #sales", category="communication"),
        )
        result = await client.before_execute("send_slack", {"channel": "#sales"}, ctx)

        call_args = mock_instance.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["agent_id"] == "slack-bot"
        assert payload["metadata"] == {"workspace": "acme"}
        assert payload["display_hints"]["title"] == "Post in #sales"


@pytest.mark.asyncio
async def test_before_execute_dict_without_metadata(client):
    """Dict context without metadata sends empty metadata."""
    with patch("dharahil.client.httpx.AsyncClient") as mock_client:
        mock_instance = AsyncMock()
        mock_instance.post.return_value = _mock_response()
        mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
        mock_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value = mock_instance

        result = await client.before_execute(
            "read_file",
            {"path": "/tmp/x"},
            {"agent_id": "bot", "run_id": "r3"},
        )

        call_args = mock_instance.post.call_args
        payload = call_args.kwargs["json"]
        assert payload["metadata"] == {}
        assert payload["display_hints"] is None
