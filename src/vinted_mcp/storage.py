import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .models import Listing


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        (root / "photos").mkdir(exist_ok=True, mode=0o700)
        self.db = root / "state.sqlite3"
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS drafts (
                    id TEXT PRIMARY KEY, listing TEXT NOT NULL, state TEXT NOT NULL,
                    expires REAL NOT NULL, result TEXT, mode TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        with sqlite3.connect(self.db, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def create(self, listing: Listing, mode: str):
        for photo_id in listing.photo_ids:
            self.photo_path(photo_id)
        draft_id = secrets.token_urlsafe(24)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO drafts VALUES (?, ?, 'prepared', ?, NULL, ?)",
                (draft_id, listing.model_dump_json(), time.time() + 1800, mode),
            )
        return self.get(draft_id)

    def get(self, draft_id: str):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise ValueError("Bozza inesistente")
        result = dict(row)
        result["listing"] = json.loads(result["listing"])
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def claim(self, draft_id: str, mode: str):
        # Commit before contacting Vinted: crashes and timeouts must never cause an automatic retry.
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            block = conn.execute("SELECT value FROM control WHERE key='blocked'").fetchone()
            if block and mode == "live":
                raise ValueError("Invii sospesi: controlla l'account e usa il comando locale unblock")
            recent = conn.execute("SELECT value FROM control WHERE key='last_attempt'").fetchone()
            if mode == "live" and recent and time.time() - float(recent[0]) < 60:
                raise ValueError("Attendi almeno 60 secondi fra due pubblicazioni")
            changed = conn.execute(
                "UPDATE drafts SET state='publishing' WHERE id=? AND state='prepared' AND expires>? AND mode=?",
                (draft_id, time.time(), mode),
            ).rowcount
            if not changed:
                raise ValueError("Bozza scaduta, già inviata oppure creata in un'altra modalità")
            conn.execute("INSERT OR REPLACE INTO control VALUES ('last_attempt', ?)", (str(time.time()),))
        return self.get(draft_id)

    def finish(self, draft_id: str, state: str, result: dict):
        with self.connect() as conn:
            conn.execute(
                "UPDATE drafts SET state=?, result=? WHERE id=?", (state, json.dumps(result), draft_id)
            )

    def block(self):
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO control VALUES ('blocked', '1')")

    def unblock(self):
        with self.connect() as conn:
            conn.execute("DELETE FROM control WHERE key='blocked'")

    def photo_path(self, photo_id: str):
        if len(photo_id) != 64 or any(c not in "0123456789abcdef" for c in photo_id):
            raise ValueError("ID foto non valido")
        path = self.root / "photos" / (photo_id + ".jpg")
        if not path.is_file():
            raise ValueError("Foto non trovata: importa prima gli allegati")
        return path
