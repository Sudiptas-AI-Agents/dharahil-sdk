from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx

from .context import ToolContext
from .interceptor import InterceptorAction, InterceptorResult, ToolExecutionInterceptor
from .redaction import redact


class DharaHILClient(ToolExecutionInterceptor):
    """
    Concrete interceptor implementation that talks to the DharaHIL gateway.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        tenant_id: str,
        app_id: str,
        environment: str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.tenant_id = tenant_id
        self.app_id = app_id
        self.environment = environment

    async def before_execute(
        self, tool_name: str, tool_args: Dict[str, Any], context: Union[Dict[str, Any], ToolContext]
    ) -> InterceptorResult:
        # Normalize: accept both ToolContext and plain dict
        if isinstance(context, ToolContext):
            ctx = context.to_dict()
        else:
            ctx = context

        redacted_args, _ = redact(tool_args)

        risk_level = ctx.get("risk_level", "MEDIUM")
        tags: List[str] = ctx.get("tags", [])

        payload = {
            "tenant_id": self.tenant_id,
            "app_id": self.app_id,
            "agent_id": ctx.get("agent_id", "unknown"),
            "run_id": ctx.get("run_id", "run"),
            "step_id": ctx.get("step_id", "step"),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_args_redacted": redacted_args,
            "context_summary": ctx.get("context_summary", ""),
            "risk_level": risk_level,
            "environment": self.environment,
            "tags": tags,
            "idempotency_key": ctx.get("idempotency_key", ctx.get("run_id", "run")),
            "webhook": {
                "decision_url": ctx.get("decision_url", ""),
            },
            "metadata": ctx.get("metadata", {}),
            "display_hints": ctx.get("display"),
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v1/requests",
                json=payload,
                headers={"X-DHARA-API-KEY": self.api_key},
            )

        if resp.status_code == 400:
            # Legacy gateway: parse detail to determine ALLOW vs DENY
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = resp.text
            if "DENY" in str(detail):
                return InterceptorResult(action=InterceptorAction.DENY, reason=str(detail))
            return InterceptorResult(action=InterceptorAction.ALLOW, reason=str(detail))

        resp.raise_for_status()
        data = resp.json()

        # New gateway format: returns {"action": "ALLOW"|"DENY", "request_id": null}
        action = data.get("action")
        if action and not data.get("request_id"):
            mapped = InterceptorAction(action) if action in InterceptorAction.__members__ else InterceptorAction.ALLOW
            return InterceptorResult(action=mapped, reason=f"Policy decision: {action}")

        request_id = data["request_id"]
        return InterceptorResult(
            action=InterceptorAction.REQUIRE_APPROVAL,
            request_id=request_id,
            reason="Awaiting human approval",
        )

    async def get_request(self, request_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.base_url}/v1/requests/{request_id}",
                headers={"X-DHARA-API-KEY": self.api_key},
            )
        resp.raise_for_status()
        return resp.json()

    async def wait_for_decision(
        self,
        request_id: str,
        *,
        timeout_seconds: int = 600,
        poll_interval_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """
        Polls DharaHIL until a decision is present or timeout elapses.

        Returns the latest request payload from GET /v1/requests/{id} which
        includes last_decision / last_decision_note / last_decision_revise_input.
        """
        import asyncio
        import time

        deadline = time.time() + timeout_seconds
        last = None

        while time.time() < deadline:
            last = await self.get_request(request_id)
            if last.get("last_decision") is not None:
                return last
            await asyncio.sleep(poll_interval_seconds)

        raise TimeoutError(f"No decision for request {request_id} within {timeout_seconds} seconds")

    async def submit_proposal_update(
        self,
        request_id: str,
        *,
        version_from: int,
        updated_tool_name: str,
        updated_tool_args: Dict[str, Any],
        updated_tool_args_redacted: Dict[str, Any],
        updated_context_summary: str,
        updated_risk_level: str,
        tags: List[str],
        display_hints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "version_from": version_from,
            "updated_tool_name": updated_tool_name,
            "updated_tool_args": updated_tool_args,
            "updated_tool_args_redacted": updated_tool_args_redacted,
            "updated_context_summary": updated_context_summary,
            "updated_risk_level": updated_risk_level,
            "tags": tags,
        }
        if display_hints is not None:
            payload["display_hints"] = display_hints
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v1/requests/{request_id}/proposal",
                json=payload,
                headers={"X-DHARA-API-KEY": self.api_key},
            )
        resp.raise_for_status()
        return resp.json()


# Backward compatibility
DharaClient = DharaHILClient
