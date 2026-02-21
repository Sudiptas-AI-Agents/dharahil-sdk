# dharahil-sdk

**Python SDK for [DharaHIL](https://github.com/Sudiptas-AI-Agents/DharaHIL) — Human-in-the-Loop Tool Execution Approval**

Intercept AI agent tool calls, route high-risk actions through human approval, and resume execution after a decision.

## Installation

```bash
pipx install "git+https://github.com/Sudiptas-AI-Agents/dharahil-sdk.git"
```

**Requirements:** Python 3.10+

## Quick Start

```python
from dharahil.client import DharaHILClient
from dharahil.langgraph_adapter import wrap_tool_with_dharahil

# Initialize the client
client = DharaHILClient(
    base_url="https://dharahil-gateway.sudiptadhara.in",
    api_key="your-api-key",
    tenant_id="your-tenant-id",
    app_id="your-app-id",
    environment="production",
)

# Wrap any async tool function
async def send_email(to: str, subject: str, body: str) -> str:
    # your implementation
    return f"Sent email to {to}"

wrapped_send_email = wrap_tool_with_dharahil(
    send_email,
    dhara_client=client,
    tool_name="send_email",
)
```

When used inside a LangGraph `ToolNode`, the wrapped tool automatically:
1. Sends the tool call to the DharaHIL gateway for policy evaluation
2. If the policy returns `ALLOW` — executes immediately
3. If the policy returns `REQUIRE_APPROVAL` — calls `langgraph.interrupt()` to pause the graph
4. When the human approves, the graph resumes and the tool executes

## Components

### `DharaHILClient`

The main client that communicates with the DharaHIL gateway.

```python
client = DharaHILClient(
    base_url="https://dharahil-gateway.sudiptadhara.in",
    api_key="your-api-key",
    tenant_id="your-tenant-id",
    app_id="your-app-id",
    environment="production",
)

# Submit a tool call for policy evaluation
result = await client.before_execute(
    tool_name="send_email",
    tool_args={"to": "user@example.com", "subject": "Hello"},
    context={
        "agent_id": "my-agent",
        "run_id": "run-001",
        "step_id": "step-001",
        "risk_level": "HIGH",
        "context_summary": "Agent wants to send an email",
    },
)
# result.action: ALLOW, DENY, or REQUIRE_APPROVAL

# Poll for a decision (if REQUIRE_APPROVAL)
decision = await client.wait_for_decision(
    result.request_id,
    timeout_seconds=600,
    poll_interval_seconds=2.0,
)

# Submit a revised proposal
await client.submit_proposal_update(
    request_id=result.request_id,
    version_from=1,
    updated_tool_name="send_email",
    updated_tool_args={"to": "admin@example.com"},
    updated_tool_args_redacted={"to": "admin@example.com"},
    updated_context_summary="Updated recipient",
    updated_risk_level="HIGH",
    tags=["email"],
)
```

### `wrap_tool_with_dharahil`

LangGraph adapter that wraps a tool function for automatic interception.

```python
from dharahil.langgraph_adapter import wrap_tool_with_dharahil

wrapped_tool = wrap_tool_with_dharahil(
    your_tool_fn,
    dhara_client=client,
    tool_name="your_tool_name",
)
```

Pass DharaHIL context via the `_dhara_context` kwarg:

```python
result = await wrapped_tool(
    to="user@example.com",
    _dhara_context={
        "agent_id": "my-agent",
        "run_id": "run-001",
        "step_id": "step-001",
        "risk_level": "HIGH",
        "context_summary": "Sending email to user",
        "tags": ["email", "outbound"],
    },
)
```

### `ToolExecutionInterceptor`

Abstract base class for building custom interceptors. `DharaHILClient` extends this.

### Automatic Redaction

The SDK automatically redacts sensitive fields in tool arguments before sending them to the gateway. Fields like `api_key`, `token`, `password`, and high-entropy strings (>12 chars) are replaced with `[REDACTED]`.

```python
from dharahil.redaction import redact

redacted_args, redacted_keys = redact({
    "to": "user@example.com",
    "api_key": "sk-abc123xyz",
})
# redacted_args = {"to": "user@example.com", "api_key": "[REDACTED]"}
# redacted_keys = ["api_key"]
```

## Dependencies

- `httpx >= 0.27.0` — async HTTP client
- `pydantic >= 2.7.0` — data validation

LangGraph is required only if using `wrap_tool_with_dharahil`.

## License

MIT
