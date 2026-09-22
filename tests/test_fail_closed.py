"""The client must never run a tool on an ambiguous gateway answer, and must
never let one approval cover a different call."""
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from dharahil.client import DharaHILClient
from dharahil.context import ToolContext
from dharahil.interceptor import InterceptorAction


def _client():
    return DharaHILClient(base_url="http://gw", api_key="k", tenant_id="t", app_id="a", environment="dev")


async def _call(client, response, tool="send_email", args=None, ctx=None):
    request = httpx.Request("POST", "http://gw/v1/requests")
    with patch("dharahil.client.httpx.AsyncClient") as mock_client:
        inst = AsyncMock()
        inst.post.return_value = httpx.Response(response[0], json=response[1], request=request)
        inst.__aenter__ = AsyncMock(return_value=inst)
        inst.__aexit__ = AsyncMock(return_value=False)
        mock_client.return_value = inst
        result = await client.before_execute(tool, args or {"to": "x"}, ctx or ToolContext(agent_id="a", run_id="r"))
        return result, inst.post.call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_distinct_calls_get_distinct_keys_with_tool_context():
    c = _client()
    _, p1 = await _call(c, (200, {"action": "ALLOW", "request_id": None}), "send_email", {"to": "a"})
    _, p2 = await _call(c, (200, {"action": "ALLOW", "request_id": None}), "delete_repo", {"to": "a"})
    _, p3 = await _call(c, (200, {"action": "ALLOW", "request_id": None}), "send_email", {"to": "a"})
    assert p1["idempotency_key"] and p1["idempotency_key"] != p2["idempotency_key"]
    assert p1["idempotency_key"] == p3["idempotency_key"]  # a retry reuses its request


@pytest.mark.asyncio
async def test_missing_run_id_is_unique_per_client():
    _, p1 = await _call(_client(), (200, {"action": "ALLOW", "request_id": None}), ctx={"agent_id": "a"})
    _, p2 = await _call(_client(), (200, {"action": "ALLOW", "request_id": None}), ctx={"agent_id": "a"})
    assert p1["run_id"].startswith("run-") and p1["run_id"] != p2["run_id"]


@pytest.mark.asyncio
async def test_unknown_action_is_denied():
    result, _ = await _call(_client(), (200, {"action": "REQUIRE-APPROVAL", "request_id": None}))
    assert result.action == InterceptorAction.DENY


@pytest.mark.asyncio
async def test_gateway_error_raises_instead_of_allowing():
    with pytest.raises(httpx.HTTPStatusError):
        await _call(_client(), (400, {"detail": "something odd"}))
