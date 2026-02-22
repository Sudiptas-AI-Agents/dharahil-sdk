from __future__ import annotations

from typing import Any, Callable, Dict, Awaitable

from langgraph.graph import interrupt

from .client import DharaHILClient
from .interceptor import InterceptorAction
from .redaction import redact


ToolCallable = Callable[..., Awaitable[Any]]


def wrap_tool_with_dharahil(
    tool: ToolCallable,
    *,
    dhara_client: DharaHILClient,
    tool_name: str,
) -> ToolCallable:
    """
    Wrap a LangGraph tool callable so that DharaHIL intercepts execution.

    The wrapper handles the full approval lifecycle including revisions:

    1. Calls ``before_execute`` — if ALLOW, runs immediately; if DENY, raises.
    2. If REQUIRE_APPROVAL, pauses via ``interrupt()`` with the request details.
    3. The orchestrator resumes the graph with a decision payload:
       - ``{"decision": "approve"}`` → execute the tool
       - ``{"decision": "reject", "note": "..."}`` → raise RuntimeError
       - ``{"decision": "revise", "revise_input": "...", "updated_args": {...}}``
         → submit updated proposal, then pause again for the next decision
    4. Revision loop repeats until the human approves or rejects.

    Usage::

        wrapped = wrap_tool_with_dharahil(send_email, dhara_client=client, tool_name="send_email")
    """

    async def wrapped_tool(*args: Any, **kwargs: Any) -> Any:
        context: Dict[str, Any] = kwargs.pop("_dhara_context", {})

        result = await dhara_client.before_execute(tool_name, kwargs, context)

        if result.action == InterceptorAction.ALLOW:
            return await tool(*args, **kwargs)
        if result.action == InterceptorAction.DENY:
            raise RuntimeError(f"DharaHIL denied tool {tool_name}: {result.reason}")

        # REQUIRE_APPROVAL: enter the approval / revision loop.
        request_id = result.request_id
        current_version = 1  # initial version from create_request

        # First interrupt: tell the orchestrator we need approval.
        pause_payload = {
            "request_id": request_id,
            "tool_name": tool_name,
            "context": context,
            "expires_at": result.expires_at,
            "type": "approval_required",
        }
        decision_payload = interrupt(pause_payload)

        while True:
            decision = decision_payload.get("decision")

            if decision == "approve":
                # If the orchestrator provided updated args, use those.
                updated_args = decision_payload.get("updated_args")
                if updated_args:
                    kwargs.update(updated_args)
                return await tool(*args, **kwargs)

            if decision == "reject":
                raise RuntimeError(
                    f"Tool {tool_name} rejected by human: {decision_payload.get('note')}"
                )

            if decision == "revise":
                # The human wants changes. Extract revision instructions.
                revise_input = decision_payload.get("revise_input", "")
                revise_patch = decision_payload.get("revise_patch", {})
                updated_args = decision_payload.get("updated_args")

                if updated_args:
                    # The orchestrator already computed the new args — submit proposal.
                    kwargs.update(updated_args)
                    redacted_args, _ = redact(kwargs)
                    proposal_resp = await dhara_client.submit_proposal_update(
                        request_id,
                        version_from=current_version,
                        updated_tool_name=tool_name,
                        updated_tool_args=kwargs,
                        updated_tool_args_redacted=redacted_args,
                        updated_context_summary=context.get("context_summary", ""),
                        updated_risk_level=context.get("risk_level", "MEDIUM"),
                        tags=context.get("tags", []),
                    )
                    current_version = proposal_resp.get("version", current_version + 1)

                    # Check if re-evaluated policy auto-resolved.
                    new_status = proposal_resp.get("status")
                    if new_status == "AUTO_ALLOWED":
                        return await tool(*args, **kwargs)
                    if new_status == "AUTO_DENIED":
                        raise RuntimeError(
                            f"DharaHIL denied revised tool {tool_name}: policy auto-denied"
                        )

                    # Still needs approval — interrupt again.
                    pause_payload = {
                        "request_id": request_id,
                        "tool_name": tool_name,
                        "context": context,
                        "expires_at": result.expires_at,
                        "version": current_version,
                        "type": "revised_proposal_pending",
                    }
                    decision_payload = interrupt(pause_payload)
                    continue

                # No updated_args yet — ask the orchestrator to compute them.
                # Interrupt with the revision instructions so the agent can act.
                revision_payload = {
                    "request_id": request_id,
                    "tool_name": tool_name,
                    "context": context,
                    "expires_at": result.expires_at,
                    "version": current_version,
                    "type": "revision_requested",
                    "revise_input": revise_input,
                    "revise_patch": revise_patch,
                    "current_args": dict(kwargs),
                }
                decision_payload = interrupt(revision_payload)
                continue

            raise RuntimeError(f"Invalid decision '{decision}' from DharaHIL")

    return wrapped_tool
