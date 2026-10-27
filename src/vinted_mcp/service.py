from .models import Listing
from .vinted import Publisher, VintedError


class ListingService:
    def __init__(self, settings, store, publisher=None):
        self.settings, self.store = settings, store
        self.publisher = publisher or Publisher(settings, store)

    async def publish(self, draft_id: str):
        previous = self.store.get(draft_id)
        if previous["state"] in {"published", "simulated"}:
            return previous["result"]  # repeated button clicks do not resend
        draft = self.store.claim(draft_id, self.settings.mode)
        try:
            result = await self.publisher.publish(draft_id, Listing.model_validate(draft["listing"]))
        except Exception as exc:  # noqa: BLE001 -- uncertain writes must stop and redact all unexpected errors
            if not isinstance(exc, VintedError) or exc.stop:
                self.store.block()
            # Do not echo exceptions/HTTP bodies/cookies/URLs to the model or logs.
            message = (
                str(exc)
                if isinstance(exc, VintedError)
                else "Errore durante l'invio: controlla Vinted manualmente"
            )
            detail = self.store.get(draft_id)["result"] or {}
            detail["error"] = message
            self.store.finish(draft_id, "needs_review", detail)
            return {"state": "needs_review", **detail}
        self.store.finish(draft_id, "simulated" if result["simulated"] else "published", result)
        return result
