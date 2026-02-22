"""Tests for DharaHILClient.submit_proposal_update, focusing on display_hints handling."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from dharahil.client import DharaHILClient


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_client():
    return DharaHILClient(
        base_url="http://test:4990",
        api_key="test-key",
        tenant_id="t1",
        app_id="a1",
        environment="dev",
    )


@patch("dharahil.client.httpx.AsyncClient")
def test_submit_proposal_update_without_display_hints(mock_client_cls):
    """Omitting display_hints must not include the key in the outgoing payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"request_id": "r1", "version": 2, "status": "PENDING"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    client = _make_client()
    result = _run(
        client.submit_proposal_update(
            "req-123",
            version_from=1,
            updated_tool_name="send_email",
            updated_tool_args={"to": "bob@example.com"},
            updated_tool_args_redacted={"to": "bob@example.com"},
            updated_context_summary="Sending email",
            updated_risk_level="MEDIUM",
            tags=["external"],
        )
    )

    call_args = mock_client.post.call_args
    sent_payload = call_args.kwargs["json"]

    assert "display_hints" not in sent_payload
    assert sent_payload["version_from"] == 1
    assert sent_payload["updated_tool_name"] == "send_email"
    assert sent_payload["updated_tool_args"] == {"to": "bob@example.com"}
    assert sent_payload["updated_tool_args_redacted"] == {"to": "bob@example.com"}
    assert sent_payload["updated_context_summary"] == "Sending email"
    assert sent_payload["updated_risk_level"] == "MEDIUM"
    assert sent_payload["tags"] == ["external"]
    assert result == {"request_id": "r1", "version": 2, "status": "PENDING"}


@patch("dharahil.client.httpx.AsyncClient")
def test_submit_proposal_update_with_display_hints(mock_client_cls):
    """Providing display_hints must include it verbatim in the outgoing payload."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"request_id": "r1", "version": 2, "status": "PENDING"}
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client

    display_hints = {
        "title": "Send Email",
        "sections": [
            {"label": "Recipient", "value": "bob@example.com"},
            {"label": "Subject", "value": "Hello"},
        ],
    }

    client = _make_client()
    result = _run(
        client.submit_proposal_update(
            "req-123",
            version_from=1,
            updated_tool_name="send_email",
            updated_tool_args={"to": "bob@example.com", "subject": "Hello"},
            updated_tool_args_redacted={"to": "bob@example.com", "subject": "Hello"},
            updated_context_summary="Sending email to bob",
            updated_risk_level="MEDIUM",
            tags=["external"],
            display_hints=display_hints,
        )
    )

    call_args = mock_client.post.call_args
    sent_payload = call_args.kwargs["json"]

    assert "display_hints" in sent_payload
    assert sent_payload["display_hints"]["title"] == "Send Email"
    assert sent_payload["display_hints"]["sections"] == [
        {"label": "Recipient", "value": "bob@example.com"},
        {"label": "Subject", "value": "Hello"},
    ]
    assert sent_payload["version_from"] == 1
    assert sent_payload["updated_tool_name"] == "send_email"
    assert sent_payload["updated_risk_level"] == "MEDIUM"
    assert sent_payload["tags"] == ["external"]
    assert result == {"request_id": "r1", "version": 2, "status": "PENDING"}
