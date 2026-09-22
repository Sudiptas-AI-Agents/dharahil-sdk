"""CrewAI adapter: put DharaHIL in front of a CrewAI tool.

Duck-typed on CrewAI's ``BaseTool`` (``.name`` and a sync ``._run``), so
``crewai`` is not a dependency of this package.

    from dharahil.crewai import require_approval

    send_email = require_approval(SendEmailTool(), dhara_client=client, context=ToolContext(...))
"""
from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar, Union

from .client import DharaHILClient, ReviseCallback
from .context import ToolContext

T = TypeVar("T")
Context = Union[ToolContext, Dict[str, Any], Callable[[Dict[str, Any]], Union[ToolContext, Dict[str, Any]]]]

_EXECUTE = {"ALLOW", "APPROVED", "AUTO_ALLOWED"}


def _run_sync(coro: Awaitable[T]) -> T:
    """Run a coroutine from sync code, even if the caller already has a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _blocked_message(tool_name: str, outcome: Dict[str, Any]) -> str:
    action = outcome.get("action")
    if action == "REJECTED":
        note = outcome.get("note")
        return f"Not executed: a human reviewer rejected {tool_name}" + (f": {note}" if note else ".")
    if action == "REVISE_REQUESTED":
        return (
            f"Not executed: the reviewer asked for changes to {tool_name}: "
            f"{outcome.get('revise_input') or '(no instructions)'}. Adjust the arguments and try again."
        )
    if action == "EXPIRED":
        return f"Not executed: nobody approved {tool_name} before the request expired."
    return f"Not executed: policy blocked {tool_name} ({action}). {outcome.get('reason') or ''}".strip()


def require_approval(
    tool: T,
    *,
    dhara_client: DharaHILClient,
    context: Context,
    on_revise: Optional[ReviseCallback] = None,
    poll_interval_seconds: float = 2.0,
) -> T:
    """Wrap ``tool._run`` so it runs only after DharaHIL allows or a human approves.

    Executes with the args the human approved (they may have edited them).
    When blocked, returns a sentence explaining why instead of raising, so the
    agent can read it and adapt.
    """
    original = tool._run  # type: ignore[attr-defined]
    tool_name = getattr(tool, "name", None) or type(tool).__name__

    def _run(*args: Any, **kwargs: Any) -> Any:
        ctx = context(kwargs) if callable(context) else context
        outcome = _run_sync(
            dhara_client.run_approval_loop(
                tool_name=tool_name,
                tool_args=kwargs,
                context=ctx,
                on_revise=on_revise,
                poll_interval_seconds=poll_interval_seconds,
            )
        )
        if outcome.get("action") in _EXECUTE:
            return original(*args, **(outcome.get("tool_args") or kwargs))
        return _blocked_message(tool_name, outcome)

    # CrewAI tools are pydantic models; bypass field validation for the method swap.
    object.__setattr__(tool, "_run", _run)
    return tool
