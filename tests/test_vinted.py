import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from vinted_mcp.vinted import Publisher, VintedError


def test_live_adapter_contract(store, settings, listing):
    settings.session_file.write_text(json.dumps({"cookies": {"session": "secret"}, "csrf_token": "csrf"}))
    live = replace(settings, mode="live", enable_live=True)
    draft = store.create(listing, "live")
    calls = []

    def handler(request):
        calls.append(request)
        assert request.headers["X-CSRF-Token"] == "csrf"
        assert request.headers["Cookie"] == "session=secret"
        if request.url.path == "/api/v2/photos":
            assert b"image/jpeg" in request.content
            return httpx.Response(200, json={"photo": {"id": 22}})
        body = json.loads(request.content)
        if request.url.path.endswith("/completion"):
            assert "assigned_photos" not in body["draft"]
            assert body["draft"]["photos"] == [{"id": 22, "orientation": 0}]
            assert body["draft"]["title"] == listing.title
            return httpx.Response(200, json={"item": {"id": 99}})
        assert body["draft"]["assigned_photos"][0]["id"] == 22
        return httpx.Response(200, json={"draft": {"id": 55}})

    result = asyncio.run(Publisher(live, store, httpx.MockTransport(handler)).publish(draft["id"], listing))
    assert result["url"] == "https://www.vinted.it/items/99"
    assert len(calls) == 3
    assert "secret" not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_no_retry_or_response_body_leak(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text="secret cookie password")

    async def run():
        async with httpx.AsyncClient(
            base_url="https://www.vinted.it", transport=httpx.MockTransport(handler)
        ) as c:
            with pytest.raises(VintedError) as error:
                await Publisher.request(c, "/api/v2/photos")
            assert error.value.stop
            assert "secret" not in str(error.value)

    asyncio.run(run())
    assert len(calls) == 1
