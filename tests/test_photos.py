import io
import socket

import pytest
from PIL import Image

from vinted_mcp.photos import normalize_photo, safe_photo_url


def test_photo_removes_exif():
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[270] = "Private metadata"
    Image.new("RGB", (100, 100), "red").save(buf, "JPEG", exif=exif)
    result = normalize_photo(buf.getvalue())
    with Image.open(io.BytesIO(result)) as image:
        assert not image.getexif()
        assert image.format == "JPEG"


@pytest.mark.parametrize(
    "url",
    [
        "http://files.oaiusercontent.com/x",
        "https://localhost/x",
        "https://files.oaiusercontent.com.evil.example/x",
        "https://user:pass@files.oaiusercontent.com/x",
        "https://files.oaiusercontent.com:8080/x",
    ],
)
def test_untrusted_downloads_rejected(url):
    with pytest.raises(ValueError):
        safe_photo_url(url, ("files.oaiusercontent.com",))


def test_private_dns_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError):
        safe_photo_url("https://files.oaiusercontent.com/x", ("files.oaiusercontent.com",))


def test_invalid_image_rejected():
    with pytest.raises(ValueError):
        normalize_photo(b"not an image")
