import hashlib
import io
import ipaddress
import socket
import warnings
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageOps

from .models import PhotoFile

MAX_BYTES = 10 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000


def safe_photo_url(url: str, allowed_hosts: tuple[str, ...]):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Host foto non autorizzato; configura PHOTO_DOWNLOAD_HOSTS con host esatti")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Indirizzo foto privato o non pubblico")


def normalize_photo(raw: bytes) -> bytes:
    if len(raw) > MAX_BYTES:
        raise ValueError("Foto troppo grande (massimo 10 MB)")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Sono consentite foto JPEG, PNG e WebP")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2400, 2400))
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                return output.getvalue()  # no EXIF/GPS metadata
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError("Foto non valida o dimensioni eccessive") from None


async def import_photo(file: PhotoFile, store, settings):
    safe_photo_url(file.download_url, settings.photo_hosts)
    try:
        # No Vinted credentials here, no redirects, no environment proxy credentials.
        async with (
            httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client,
            client.stream("GET", file.download_url) as response,
        ):
            if response.status_code != 200:
                raise ValueError("Allegato non scaricabile; allegalo di nuovo se il link è scaduto")
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    raise ValueError("Foto troppo grande")
    except httpx.HTTPError:
        raise ValueError("Download foto fallito") from None
    data = normalize_photo(bytes(raw))
    photo_id = hashlib.sha256(data).hexdigest()
    target = store.root / "photos" / (photo_id + ".jpg")
    target.write_bytes(data)
    return {"photo_id": photo_id, "bytes": len(data)}
