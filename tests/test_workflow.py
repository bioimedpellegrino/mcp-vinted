import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from vinted_mcp.service import ListingService
from vinted_mcp.vinted import VintedError


def test_mock_double_click_sends_once(store, settings, listing):
    class Fake:
        calls = 0

        async def publish(self, draft_id, listing):
            self.calls += 1
            return {"simulated": True, "item_id": "mock"}

    publisher = Fake()
    service = ListingService(settings, store, publisher)
    draft = store.create(listing, "mock")
    first = asyncio.run(service.publish(draft["id"]))
    assert asyncio.run(service.publish(draft["id"])) == first
    assert publisher.calls == 1
    assert store.get(draft["id"])["state"] == "simulated"


def test_concurrent_claims_and_restart_do_not_resend(store, listing):
    draft = store.create(listing, "mock")

    def claim(_):
        try:
            store.claim(draft["id"], "mock")
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(claim, range(4))) == 1
    from vinted_mcp.storage import Store

    with pytest.raises(ValueError):
        Store(store.root).claim(draft["id"], "mock")


def test_expired_and_cross_mode_drafts_are_rejected(store, listing):
    draft = store.create(listing, "mock")
    with pytest.raises(ValueError):
        store.claim(draft["id"], "live")
    with store.connect() as conn:
        conn.execute("UPDATE drafts SET expires=0")
    with pytest.raises(ValueError):
        store.claim(draft["id"], "mock")


def test_uncertain_outcome_blocks_future_live_sends(store, settings, listing):
    class Timeout:
        async def publish(self, draft_id, listing):
            raise VintedError("Esito incerto", stop=True)

    live = replace(settings, mode="live", enable_live=True)
    service = ListingService(live, store, Timeout())
    draft = store.create(listing, "live")
    result = asyncio.run(service.publish(draft["id"]))
    assert result["state"] == "needs_review"
    other = store.create(listing, "live")
    with pytest.raises(ValueError, match="sospesi"):
        asyncio.run(service.publish(other["id"]))
    store.unblock()
    with pytest.raises(ValueError):
        store.claim(draft["id"], "live")


def test_missing_or_traversal_photo_rejected(store, listing):
    with pytest.raises(ValueError):
        store.photo_path("../session.json")
    with pytest.raises(ValueError):
        store.create(listing.model_copy(update={"photo_ids": ["a" * 64]}), "mock")
