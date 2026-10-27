"""Experimental web adapter: endpoint contracts are not a supported public API.

Only photos, private draft creation and its completion are used. No relisting,
deletion, bulk jobs, challenge solving, proxies or browser fingerprint spoofing.
"""

import json
from uuid import uuid4

import httpx

from .models import Listing


class VintedError(Exception):
    def __init__(self, message: str, *, stop=False):
        super().__init__(message)
        self.stop = stop


class Publisher:
    def __init__(self, settings, store, transport=None):
        self.settings, self.store, self.transport = settings, store, transport

    async def publish(self, draft_id: str, listing: Listing):
        if self.settings.mode == "mock":
            return {
                "simulated": True,
                "item_id": "mock-" + draft_id,
                "message": "Simulazione completata: nessun annuncio inviato a Vinted",
            }
        self.settings.validate()
        try:
            session = json.loads(self.settings.session_file.read_text(encoding="utf-8"))
            cookies = session["cookies"]
            csrf = session["csrf_token"]
            if not isinstance(cookies, dict) or not cookies or not isinstance(csrf, str) or not csrf:
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise VintedError("Sessione locale mancante o non valida", stop=True) from None
        headers = {
            "Accept": "application/json",
            "X-CSRF-Token": csrf,
            "Origin": self.settings.base_url,
            "Referer": self.settings.base_url + "/items/new",
        }
        if session.get("anon_id"):
            headers["X-Anon-Id"] = session["anon_id"]
        session_id = str(uuid4())
        async with httpx.AsyncClient(
            base_url=self.settings.base_url,
            cookies=cookies,
            headers=headers,
            timeout=30,
            follow_redirects=False,
            trust_env=False,
            transport=self.transport,
        ) as client:
            photos = []
            for photo_id in listing.photo_ids:
                photo = self.store.photo_path(photo_id).read_bytes()
                response = await self.request(
                    client,
                    "/api/v2/photos",
                    data={"type": "item", "temp_uuid": session_id},
                    files={"photo": ("photo.jpg", photo, "image/jpeg")},
                )
                entry = response.get("photo", response)
                photos.append({"id": self.numeric_id(entry.get("id")), "orientation": 0})
            item = listing.model_dump(
                mode="json",
                exclude={"photo_ids", "category_label", "condition_label", "size_label", "package_label"},
            )
            item.update(
                {
                    "id": None,
                    "temp_uuid": session_id,
                    "assigned_photos": photos,
                    "shipment_prices": {"domestic": None, "international": None},
                }
            )
            if listing.size_id:
                item["item_attributes"] = [{"id": "size", "ids": [listing.size_id]}]
            created = await self.request(
                client,
                "/api/v2/item_upload/drafts",
                json={"draft": item, "parcel": None, "upload_session_id": session_id},
            )
            entry = created.get("draft", created.get("item", created))
            remote_id = self.numeric_id(entry.get("id"))
            # Save the remote draft ID before completion, useful for manual reconciliation.
            self.store.finish(draft_id, "publishing", {"remote_draft_id": remote_id})
            item.pop("assigned_photos")
            item.update({"id": remote_id, "photos": photos})
            completed = await self.request(
                client,
                f"/api/v2/item_upload/drafts/{remote_id}/completion",
                json={"draft": item, "parcel": None, "push_up": False, "upload_session_id": session_id},
            )
            entry = completed.get("item", completed.get("draft", completed))
            item_id = self.numeric_id(entry.get("id"))
            return {
                "simulated": False,
                "item_id": item_id,
                "url": f"{self.settings.base_url}/items/{item_id}",
            }

    @staticmethod
    def numeric_id(value):
        if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
            raise VintedError("Risposta Vinted inattesa: verifica manualmente prima di riprovare", stop=True)
        return int(value)

    @staticmethod
    async def request(client, path, **kwargs):
        try:
            response = await client.post(path, **kwargs)
        except httpx.HTTPError:
            raise VintedError(
                "Esito incerto: controlla Vinted manualmente; nessun retry automatico", stop=True
            ) from None
        if response.status_code in {401, 403, 429}:
            raise VintedError(
                f"Vinted ha fermato la richiesta (HTTP {response.status_code}). Controlla l'account.",
                stop=True,
            )
        if not 200 <= response.status_code < 300:
            raise VintedError(
                f"Invio non confermato (HTTP {response.status_code}); controlla bozze e annunci su Vinted",
                stop=True,
            )
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("code", 0) not in (0, None):
                raise ValueError()
            return result
        except ValueError:
            raise VintedError("Risposta Vinted non riconosciuta; invii sospesi", stop=True) from None
