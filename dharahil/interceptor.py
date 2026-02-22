from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Union

from .context import ToolContext


class InterceptorAction(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass
class InterceptorResult:
    action: InterceptorAction
    request_id: Optional[str] = None
    reason: Optional[str] = None
    expires_at: Optional[str] = None  # ISO-8601 expiry from gateway


class ToolExecutionInterceptor:
    """
    Generic interception interface to integrate DharaHIL at the tool execution boundary.
    Framework-specific adapters (e.g. LangChain/LangGraph) should depend on this.
    """

    async def before_execute(
        self, tool_name: str, tool_args: Dict[str, Any], context: Union[Dict[str, Any], ToolContext]
    ) -> InterceptorResult:
        raise NotImplementedError


