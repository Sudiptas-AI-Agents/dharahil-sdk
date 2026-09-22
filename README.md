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

The SDK redacts the copy of the arguments that approvers see. Values under secret-looking keys (`api_key`, `token`, `password`, `secret`, …) are masked whole. Inside other strings, known credential shapes (`sk-…`, `xoxb-…`, `ghp_…`, AWS keys, JWTs) and 20+ character runs mixing letters and digits are masked in place, so ordinary prose stays readable. Nested dicts and lists are walked.

```python
from dharahil.redaction import redact

redacted, report = redact({
    "to": "user@example.com",
    "api_key": "sk-abc123xyz",
    "note": "deploy image a3f9c2e1b7d4f8e6a1c2b3d4 now",
})
# redacted == {"to": "user@example.com", "api_key": "***REDACTED***",
#              "note": "deploy image ***REDACTED*** now"}
# report["fields"] == [{"key": "api_key", "reason": "secret_key"},
#                      {"key": "note", "reason": "high_entropy"}]
```

### CrewAI

```python
from dharahil.crewai import require_approval

send_email = require_approval(
    SendEmailTool(),
    dhara_client=client,
    context=lambda args: ToolContext(
        agent_id="crew", run_id=run_id, risk_level="HIGH",
        context_summary=f"Email {args['to']}",
    ),
)
```

The tool runs only after DharaHIL allows it or a human approves, with the args the human approved. When blocked, `_run` returns a sentence explaining why, so the agent can adapt instead of crashing.

## Dependencies

- `httpx >= 0.27.0` — async HTTP client
- `pydantic >= 2.7.0` — data validation

LangGraph is required only if using `wrap_tool_with_dharahil`.

## License

MIT
