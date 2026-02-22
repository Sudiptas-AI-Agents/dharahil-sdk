from __future__ import annotations

from typing import Any, Callable, Dict, Awaitable

from langgraph.graph import interrupt

from .client import DharaHILClient
from .interceptor import InterceptorAction


ToolCallable = Callable[..., Awaitable[Any]]


def wrap_tool_with_dharahil(
    tool: ToolCallable,
    *,
    dhara_client: DharaHILClient,
    tool_name: str,
) -> ToolCallable:
    """
    Wrap a LangGraph tool callable so that DharaHIL intercepts execution.

    Usage:
        wrapped_send_email = wrap_tool_with_dharahil(send_email, dhara_client=client, tool_name="send_email")
    """

    async def wrapped_tool(*args: Any, **kwargs: Any) -> Any:
        context: Dict[str, Any] = kwargs.pop("_dhara_context", {})

        result = await dhara_client.before_execute(tool_name, kwargs, context)

        if result.action == InterceptorAction.ALLOW:
            return await tool(*args, **kwargs)
        if result.action == InterceptorAction.DENY:
            raise RuntimeError(f"DharaHIL denied tool {tool_name}: {result.reason}")

        # REQUIRE_APPROVAL: pause graph and wait for decision.
        pause_payload = {
            "request_id": result.request_id,
            "tool_name": tool_name,
            "context": context,
            "expires_at": result.expires_at,
        }
        decision_payload = await interrupt(pause_payload)

        decision = decision_payload.get("decision")
        if decision == "approve":
            return await tool(*args, **kwargs)
        if decision == "reject":
            raise RuntimeError(f"Tool {tool_name} rejected by human: {decision_payload.get('note')}")
        if decision == "revise":
            # Upstream planner should have already sent updated proposal via /proposal.
            # Here we simply proceed or abort based on flag.
            if decision_payload.get("execute", False):
                return await tool(*args, **kwargs)
            raise RuntimeError("Execution cancelled after revise")

        raise RuntimeError("Invalid decision payload from DharaHIL")

    return wrapped_tool


