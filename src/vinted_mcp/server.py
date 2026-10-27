import argparse
import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from PIL import Image

from .auth import OwnerOAuth
from .config import Settings
from .models import Listing, PhotoFile
from .photos import import_photo
from .service import ListingService
from .storage import Store

UI_URI = "ui://vinted/review.html"
INSTRUCTIONS = """Aiuta il proprietario a vendere un articolo per volta. Importa gli allegati con import_photos.
Usa get_listing_profiles per gli ID Vinted verificati: non inventarli. Se mancano, chiedi di configurarli.
Prepara titolo e descrizione in italiano; il prezzo è una stima, non una quotazione di mercato.
Chiedi marca, taglia, condizioni e difetti quando non verificabili. Chiama prepare_listing per mostrare
il riepilogo con il pulsante di conferma. Non pubblicare senza consenso esplicito. Ogni modifica richiede
una nuova bozza e nuova conferma. Non chiedere credenziali o cookie in chat. Mock è solo una simulazione.
Non riprovare invii in stato needs_review o publishing. Dopo l'invio l'utente gestisce tutto su Vinted."""


def build_server(settings: Settings, *, http=False):
    settings.validate(http=http)
    store = Store(settings.data_dir)
    service = ListingService(settings, store)
    oauth = OwnerOAuth(settings) if http else None
    kwargs = {}
    if http:
        origin = urlsplit(settings.public_url)
        kwargs = {
            "auth_server_provider": oauth,
            "auth": AuthSettings(
                issuer_url=settings.public_url,
                resource_server_url=settings.public_url + "/mcp",
                required_scopes=["vinted"],
                validate_token_resource=True,
                client_registration_options=ClientRegistrationOptions(
                    enabled=True, valid_scopes=["vinted"], default_scopes=["vinted"]
                ),
            ),
            "transport_security": TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[origin.netloc, "localhost:*", "127.0.0.1:*"],
                allowed_origins=[settings.public_url],
            ),
        }
    mcp = FastMCP(
        "Personal Vinted MCP",
        instructions=INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        stateless_http=True,
        **kwargs,
    )

    def review_result(draft):
        previews = []
        for photo_id in draft["listing"]["photo_ids"]:
            with Image.open(store.photo_path(photo_id)) as photo:
                photo.thumbnail((320, 320))
                output = io.BytesIO()
                photo.save(output, "JPEG", quality=75)
                previews.append("data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode())
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(draft, ensure_ascii=False))],
            structuredContent=draft,
            _meta={"photo_previews": previews},
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def get_status() -> dict[str, Any]:
        """Return mode and session file presence, never credentials."""
        return {
            "mode": settings.mode,
            "session_configured": settings.session_file.is_file(),
            "unofficial_api": True,
            "account_safety_guaranteed": False,
        }

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    def get_listing_profiles() -> dict[str, Any]:
        """Read verified category/brand/condition/size/package IDs and labels from local configuration.
        Mock IDs are only for simulation. Never guess real IDs or unverified item characteristics.
        """
        path = settings.data_dir / "profiles.json"
        if path.is_file():
            return {"mode": settings.mode, "profiles": json.loads(path.read_text(encoding="utf-8"))}
        if settings.mode == "mock":
            return {
                "mode": "mock",
                "profiles": [
                    {
                        "name": "Esempio SOLO simulazione",
                        "catalog_id": 1,
                        "category_label": "Magliette",
                        "brand_id": 1,
                        "brand": "Marca da verificare",
                        "status_id": 1,
                        "condition_label": "Buono (da verificare)",
                        "size_id": 1,
                        "size_label": "M (da verificare)",
                        "package_size_id": 1,
                        "package_label": "Piccolo",
                    }
                ],
            }
        return {
            "mode": "live",
            "profiles": [],
            "message": "Configura profiles.json localmente; non inventare ID",
        }

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
        meta={"openai/fileParams": ["photos"]},
    )
    async def import_photos(photos: list[PhotoFile]) -> dict[str, Any]:
        """Download 1–20 user-provided ChatGPT photo attachments and save locally without EXIF/GPS.
        Requires actual file objects from ChatGPT, never sandbox paths or invented URLs.
        """
        if not 1 <= len(photos) <= 20:
            raise ValueError("Allega da 1 a 20 foto")
        return {"photos": [await import_photo(photo, store, settings) for photo in photos]}

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False),
        meta={"openai/outputTemplate": UI_URI, "ui": {"resourceUri": UI_URI}},
    )
    def prepare_listing(listing: Listing) -> CallToolResult:
        """Save an immutable listing for 30 minutes and show summary and confirmation button.
        Does not contact Vinted. Any edits require a new draft and renewed confirmation.
        """
        return review_result(store.create(listing, settings.mode))

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
        meta={"openai/outputTemplate": UI_URI, "ui": {"resourceUri": UI_URI}},
    )
    def get_listing(draft_id: str) -> CallToolResult:
        """Read exact listing summary and publication status without contacting Vinted."""
        return review_result(store.get(draft_id))

    @mcp.tool(
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=True, openWorldHint=True, idempotentHint=True
        ),
        meta={"openai/widgetAccessible": True, "openai/visibility": "private", "ui": {"visibility": ["app"]}},
    )
    async def publish_listing(draft_id: str) -> dict[str, Any]:
        """Publish the exact reviewed draft ONLY after the user's confirmation button click.
        External write; never call proactively. Repeated successful calls return the saved result.
        """
        return await service.publish(draft_id)

    @mcp.resource(
        UI_URI,
        mime_type="text/html;profile=mcp-app",
        meta={
            "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": ["data:"]}},
            "openai/widgetDescription": "Riepilogo annuncio Vinted con foto e conferma esplicita",
        },
    )
    def review_widget() -> str:
        return Path(__file__).with_name("review.html").read_text(encoding="utf-8")

    if oauth:

        @mcp.custom_route("/owner/consent", methods=["GET", "POST"])
        async def consent(request):
            return await oauth.consent(request)

    return mcp


def main():
    parser = argparse.ArgumentParser(description="Personal Vinted MCP server")
    parser.add_argument("command", choices=["stdio", "http", "unblock"], nargs="?", default="stdio")
    args = parser.parse_args()
    settings = Settings.load()
    if args.command == "unblock":
        Store(settings.data_dir).unblock()
        print("Blocco locale rimosso. Le bozze già tentate restano bloccate per evitare duplicati.")
        return
    server = build_server(settings, http=args.command == "http")
    if args.command == "http":
        import uvicorn

        uvicorn.run(server.streamable_http_app(), host=settings.host, port=settings.port, access_log=False)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    main()
