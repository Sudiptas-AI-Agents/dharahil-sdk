from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .interceptor import InterceptorAction, InterceptorResult, ToolExecutionInterceptor
from .redaction import redact


class DharaClient(ToolExecutionInterceptor):
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
        self, tool_name: str, tool_args: Dict[str, Any], context: Dict[str, Any]
    ) -> InterceptorResult:
        redacted_args, _ = redact(tool_args)

        risk_level = context.get("risk_level", "MEDIUM")
        tags: List[str] = context.get("tags", [])

        payload = {
            "tenant_id": self.tenant_id,
            "app_id": self.app_id,
            "agent_id": context.get("agent_id", "unknown"),
            "run_id": context.get("run_id", "run"),
            "step_id": context.get("step_id", "step"),
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_args_redacted": redacted_args,
            "context_summary": context.get("context_summary", ""),
            "risk_level": risk_level,
            "environment": self.environment,
            "tags": tags,
            "idempotency_key": context.get("idempotency_key", context.get("run_id", "run")),
            "webhook": {
                "decision_url": context.get("decision_url", ""),
            },
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v1/requests",
                json=payload,
                headers={"X-DHARA-API-KEY": self.api_key},
            )

        if resp.status_code == 400:
            # Policy allowed or denied without approval; for now, treat as ALLOW
            return InterceptorResult(action=InterceptorAction.ALLOW)

        resp.raise_for_status()
        data = resp.json()
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
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{self.base_url}/v1/requests/{request_id}/proposal",
                json=payload,
                headers={"X-DHARA-API-KEY": self.api_key},
            )
        resp.raise_for_status()
        return resp.json()
