from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

import httpx

from .context import ToolContext
from .interceptor import InterceptorAction, InterceptorResult, ToolExecutionInterceptor
from .redaction import redact

# Type for the revision callback used by run_approval_loop.
# Receives (current_args, revise_input, revise_patch) and returns updated_args.
ReviseCallback = Callable[
    [Dict[str, Any], str, Dict[str, Any]], Awaitable[Dict[str, Any]]
]


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
            expires_at=data.get("expires_at"),
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
        timeout_seconds: Optional[int] = None,
        expires_at: Optional[str] = None,
        poll_interval_seconds: float = 2.0,
        after_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Polls DharaHIL until a decision is present or timeout elapses.

        Timeout is determined in priority order:
        1. ``timeout_seconds`` if provided explicitly
        2. ``expires_at`` (ISO-8601 from InterceptorResult.expires_at)
        3. Falls back to 600s (10 minutes)

        If ``after_version`` is provided, ignores any decision that was made
        before the given version (e.g. a stale "revise" from version 1 when
        the caller has already submitted version 2). This is critical for the
        revision loop: after submitting a proposal update, pass the new version
        number so we wait for the *next* decision, not the old one.

        Returns the latest request payload from GET /v1/requests/{id} which
        includes last_decision / last_decision_note / last_decision_revise_input.
        """
        import asyncio
        import time
        from datetime import datetime, timezone

        if timeout_seconds is not None:
            effective_timeout = timeout_seconds
        elif expires_at:
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
                effective_timeout = max(int(remaining) + 5, 10)  # +5s buffer, min 10s
            except (ValueError, TypeError):
                effective_timeout = 600
        else:
            effective_timeout = 600

        deadline = time.time() + effective_timeout
        last = None

        while time.time() < deadline:
            last = await self.get_request(request_id)
            has_decision = last.get("last_decision") is not None

            if has_decision and after_version is not None:
                # If the request is still on a stale decision (status is
                # REVISE_REQUESTED but we already submitted a newer version),
                # the current last_decision is from a previous round — skip it.
                current_status = last.get("status", "")
                current_version = last.get("version", 1)
                if current_status == "REVISE_REQUESTED" and current_version >= after_version:
                    # Status hasn't changed since our proposal update
                    # reset to PENDING. Keep polling.
                    has_decision = False
                elif current_status == "PENDING" and current_version >= after_version:
                    # Proposal accepted, waiting for new decision.
                    has_decision = False

            if has_decision:
                return last

            # Stop early if request reached a terminal state
            status = last.get("status", "")
            if status not in ("PENDING", "REVISE_REQUESTED"):
                return last
            await asyncio.sleep(poll_interval_seconds)

        raise TimeoutError(f"No decision for request {request_id} within {effective_timeout} seconds")

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

    async def run_approval_loop(
        self,
        *,
        tool_name: str,
        tool_args: Dict[str, Any],
        context: Union[Dict[str, Any], ToolContext],
        on_revise: Optional[ReviseCallback] = None,
        poll_interval_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """
        High-level helper that handles the full approval lifecycle including
        revision loops. Suitable for polling-mode callers (non-LangGraph).

        1. Calls ``before_execute()`` to register the request.
        2. If ALLOW / DENY, returns immediately with ``{"action": "ALLOW"}``
           or ``{"action": "DENY", "reason": "..."}``.
        3. If REQUIRE_APPROVAL, polls ``wait_for_decision()``.
        4. On approve → returns ``{"action": "APPROVED", "tool_args": {...}}``.
        5. On reject → returns ``{"action": "REJECTED", "note": "..."}``.
        6. On revise → calls ``on_revise(current_args, revise_input, revise_patch)``
           to get updated args, submits a proposal update, then loops back to 3.
        7. If ``on_revise`` is not provided and a revise decision comes in,
           returns ``{"action": "REVISE_REQUESTED", ...}`` so the caller can
           handle it manually.

        Returns a dict with at minimum ``{"action": "..."}`` plus relevant data.
        """
        if isinstance(context, ToolContext):
            ctx = context.to_dict()
        else:
            ctx = dict(context)

        result = await self.before_execute(tool_name, tool_args, ctx)

        if result.action == InterceptorAction.ALLOW:
            return {"action": "ALLOW", "tool_args": tool_args}
        if result.action == InterceptorAction.DENY:
            return {"action": "DENY", "reason": result.reason}

        request_id = result.request_id
        current_version = 1
        current_args = dict(tool_args)

        while True:
            decision_data = await self.wait_for_decision(
                request_id,
                expires_at=result.expires_at,
                poll_interval_seconds=poll_interval_seconds,
                after_version=current_version if current_version > 1 else None,
            )

            decision = decision_data.get("last_decision")
            status = decision_data.get("status", "")

            if decision == "approve" or status == "APPROVED":
                return {
                    "action": "APPROVED",
                    "request_id": request_id,
                    "tool_args": current_args,
                    "version": decision_data.get("version", current_version),
                }

            if decision == "reject" or status == "REJECTED":
                return {
                    "action": "REJECTED",
                    "request_id": request_id,
                    "note": decision_data.get("last_decision_note", ""),
                    "version": decision_data.get("version", current_version),
                }

            if status in ("AUTO_ALLOWED",):
                return {
                    "action": "AUTO_ALLOWED",
                    "request_id": request_id,
                    "tool_args": current_args,
                }

            if status in ("AUTO_DENIED",):
                return {
                    "action": "AUTO_DENIED",
                    "request_id": request_id,
                    "reason": "Policy auto-denied the revised proposal",
                }

            if status == "EXPIRED":
                return {
                    "action": "EXPIRED",
                    "request_id": request_id,
                }

            if decision == "revise" or status == "REVISE_REQUESTED":
                revise_input = decision_data.get("last_decision_revise_input", "")
                revise_patch = {}  # Gateway doesn't return patch in GET response

                if on_revise is None:
                    # No callback — return to caller so they can handle manually.
                    return {
                        "action": "REVISE_REQUESTED",
                        "request_id": request_id,
                        "revise_input": revise_input,
                        "current_args": current_args,
                        "version": current_version,
                    }

                # Call the revision callback to compute new args.
                updated_args = await on_revise(current_args, revise_input, revise_patch)
                current_args = updated_args
                redacted_args, _ = redact(current_args)

                proposal_resp = await self.submit_proposal_update(
                    request_id,
                    version_from=current_version,
                    updated_tool_name=tool_name,
                    updated_tool_args=current_args,
                    updated_tool_args_redacted=redacted_args,
                    updated_context_summary=ctx.get("context_summary", ""),
                    updated_risk_level=ctx.get("risk_level", "MEDIUM"),
                    tags=ctx.get("tags", []),
                )
                current_version = proposal_resp.get("version", current_version + 1)

                # Check if re-evaluated policy auto-resolved.
                new_status = proposal_resp.get("status")
                if new_status == "AUTO_ALLOWED":
                    return {
                        "action": "AUTO_ALLOWED",
                        "request_id": request_id,
                        "tool_args": current_args,
                    }
                if new_status == "AUTO_DENIED":
                    return {
                        "action": "AUTO_DENIED",
                        "request_id": request_id,
                        "reason": "Policy auto-denied the revised proposal",
                    }

                # Loop back to wait for the next decision on the revised proposal.
                continue

            # Unknown status — return raw data.
            return {
                "action": status or "UNKNOWN",
                "request_id": request_id,
                "raw": decision_data,
            }


# Backward compatibility
DharaClient = DharaHILClient
