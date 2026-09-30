import httpx
import pytest
import respx

from dharahil import DharaHILClient, DisplayHints


def test_choices_only_when_set():
    assert "choices" not in DisplayHints(title="t").to_dict()
    d = DisplayHints(title="t", choices=[{"id": "job", "label": "Job"}]).to_dict()
    assert d["choices"] == [{"id": "job", "label": "Job"}]


def _client():
    return DharaHILClient(base_url="https://hil.test", api_key="k", tenant_id="t", app_id="a", environment="dev")


@pytest.mark.asyncio
@respx.mock
async def test_standing_approvals_and_revoke():
    route = respx.get("https://hil.test/v1/agent/standing-approvals").mock(
        return_value=httpx.Response(200, json={"grants": [{"id": "g1"}], "policy": None}))
    assert (await _client().standing_approvals())["grants"][0]["id"] == "g1"
    assert route.calls[0].request.headers["X-DHARA-API-KEY"] == "k"
    rv = respx.delete("https://hil.test/v1/agent/grants/g1").mock(return_value=httpx.Response(204))
    await _client().revoke_grant("g1")
    assert rv.called
    respx.delete("https://hil.test/v1/agent/grants/nope").mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await _client().revoke_grant("nope")
