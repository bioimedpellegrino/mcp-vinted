import hashlib
import io

import pytest
from PIL import Image

from vinted_mcp.config import Settings
from vinted_mcp.models import Listing
from vinted_mcp.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path)


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, session_file=tmp_path / "session.json", owner_secret="x" * 40)


@pytest.fixture
def listing(store):
    buf = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buf, "JPEG")
    photo_id = hashlib.sha256(buf.getvalue()).hexdigest()
    (store.root / "photos" / (photo_id + ".jpg")).write_bytes(buf.getvalue())
    return Listing(
        title="Maglietta blu",
        description="Maglietta blu usata in buone condizioni",
        price="12.50",
        catalog_id=1,
        brand_id=1,
        brand="Esempio",
        status_id=1,
        package_size_id=1,
        photo_ids=[photo_id],
        category_label="Magliette",
        condition_label="Buono",
        size_label="M",
        package_label="Piccolo",
    )
