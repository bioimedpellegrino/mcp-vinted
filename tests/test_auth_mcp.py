import asyncio
import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from starlette.testclient import TestClient

from vinted_mcp.server import build_server


def begin_oauth(client):
    registered = client.post(
        "/register",
        json={
            "client_name": "Test client",
            "redirect_uris": ["http://localhost:9876/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registered.status_code == 201, registered.text
    client_id = registered.json()["client_id"]
    verifier = "a" * 64
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    auth = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://localhost:9876/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "vinted",
            "state": "test-state",
            "resource": "http://localhost:8000/mcp",
        },
        follow_redirects=False,
    )
    assert auth.status_code in {302, 303, 307}, auth.text
    consent = client.get(auth.headers["location"])
    assert consent.status_code == 200
    request_id = parse_qs(urlsplit(auth.headers["location"]).query)["request"][0]
    return client_id, verifier, request_id


def test_http_requires_auth_and_pkce_owner_login(settings):
    server = build_server(settings, http=True)
    with TestClient(server.streamable_http_app(), base_url="http://localhost:8000") as client:
        assert client.get("/mcp").status_code == 401
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert "S256" in metadata["code_challenge_methods_supported"]
        client_id, verifier, request_id = begin_oauth(client)
        form = {"request": request_id, "secret": settings.owner_secret}
        # Another site may not submit the owner's password on their behalf.
        assert (
            client.post("/owner/consent", data=form, headers={"origin": "https://evil.example"}).status_code
            == 403
        )
        bad = client.post(
            "/owner/consent", data={**form, "secret": "wrong"}, headers={"origin": settings.public_url}
        )
        assert bad.status_code == 403
        authorized = client.post(
            "/owner/consent", data=form, headers={"origin": settings.public_url}, follow_redirects=False
        )
        assert authorized.status_code == 303, authorized.text
        query = parse_qs(urlsplit(authorized.headers["location"]).query)
        assert query["state"] == ["test-state"]
        token_form = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": query["code"][0],
            "code_verifier": verifier,
            "redirect_uri": "http://localhost:9876/callback",
            "resource": settings.public_url + "/mcp",
        }
        wrong_pkce = client.post("/token", data={**token_form, "code_verifier": "b" * 64})
        assert wrong_pkce.status_code == 400
        token = client.post("/token", data=token_form)
        assert token.status_code == 200, token.text
        assert client.post("/token", data=token_form).status_code == 400  # single use
        headers = {
            "Authorization": "Bearer " + token.json()["access_token"],
            "Accept": "application/json, text/event-stream",
        }
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        assert "Personal Vinted MCP" in initialized.text


def test_mcp_file_schema_and_widget_confirmation(settings, listing):
    server = build_server(settings)

    async def run():
        tools = {t.name: t for t in await server.list_tools()}
        photo_tool = tools["import_photos"]
        assert photo_tool.meta["openai/fileParams"] == ["photos"]
        schema = photo_tool.inputSchema["$defs"]["PhotoFile"]
        assert set(schema["required"]) == {"download_url", "file_id"}
        assert set(schema["properties"]) == {"download_url", "file_id", "mime_type", "file_name"}
        assert tools["publish_listing"].annotations.destructiveHint
        assert tools["publish_listing"].outputSchema is not None
        assert tools["publish_listing"].meta["ui"]["visibility"] == ["app"]
        prepared = await server.call_tool("prepare_listing", {"listing": listing.model_dump(mode="json")})
        assert prepared.structuredContent["state"] == "prepared"
        assert prepared.meta["photo_previews"][0].startswith("data:image/jpeg;base64,")
        assert "secret" not in prepared.model_dump_json()
        published = await server.call_tool("publish_listing", {"draft_id": prepared.structuredContent["id"]})
        assert published[1]["simulated"] is True
        resources = await server.list_resources()
        assert resources[0].mimeType == "text/html;profile=mcp-app"

    asyncio.run(run())


def test_http_refuses_missing_secret_and_remote_cleartext(settings):
    from dataclasses import replace

    with pytest.raises(ValueError, match="SECRET"):
        build_server(replace(settings, owner_secret=""), http=True)
    with pytest.raises(ValueError, match="HTTPS"):
        build_server(replace(settings, public_url="http://example.com"), http=True)
