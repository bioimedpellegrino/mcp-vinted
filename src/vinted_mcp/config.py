import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


def local_data_dir():
    if os.name == "nt":
        return Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "VintedMCP"
    return Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "vinted-mcp"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("private")
    session_file: Path = Path("private/session.json")
    mode: str = "mock"
    base_url: str = "https://www.vinted.it"
    enable_live: bool = False
    public_url: str = "http://localhost:8000"
    owner_secret: str = ""
    photo_hosts: tuple[str, ...] = ("files.oaiusercontent.com",)
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def load(cls):
        root = local_data_dir()
        load_dotenv(os.getenv("VINTED_ENV_FILE", str(root / ".env")))
        return cls(
            data_dir=Path(os.getenv("VINTED_DATA_DIR", str(root))),
            session_file=Path(os.getenv("VINTED_SESSION_FILE", str(root / "session.json"))),
            mode=os.getenv("VINTED_MODE", "mock"),
            base_url=os.getenv("VINTED_BASE_URL", "https://www.vinted.it").rstrip("/"),
            enable_live=os.getenv("VINTED_ENABLE_UNOFFICIAL_API") == "true",
            public_url=os.getenv("MCP_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
            owner_secret=os.getenv("MCP_OWNER_SECRET", ""),
            photo_hosts=tuple(
                filter(None, os.getenv("PHOTO_DOWNLOAD_HOSTS", "files.oaiusercontent.com").split(","))
            ),
            host=os.getenv("MCP_HOST", "127.0.0.1"),
            port=int(os.getenv("MCP_PORT", "8000")),
        )

    def validate(self, http=False):
        if self.mode not in {"mock", "live"}:
            raise ValueError("VINTED_MODE must be mock or live")
        if self.mode == "live" and not self.enable_live:
            raise ValueError("Live mode requires VINTED_ENABLE_UNOFFICIAL_API=true")
        # Never let a model redirect account cookies to another service.
        if self.base_url not in {
            "https://www.vinted.it",
            "https://www.vinted.fr",
            "https://www.vinted.de",
            "https://www.vinted.es",
            "https://www.vinted.nl",
            "https://www.vinted.be",
            "https://www.vinted.pt",
            "https://www.vinted.co.uk",
        }:
            raise ValueError("Unsupported Vinted origin")
        if http:
            if len(self.owner_secret) < 32:
                raise ValueError("MCP_OWNER_SECRET must contain at least 32 characters")
            parsed = urlsplit(self.public_url)
            if parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError("MCP_PUBLIC_URL must be an origin without a path")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
            ):
                raise ValueError("Public HTTP requires HTTPS; localhost is allowed for development")
