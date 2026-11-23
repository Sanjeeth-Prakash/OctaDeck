"""Single-owner local settings and metadata-only traces."""
import os
import secrets
import sqlite3
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from time import time

from cryptography.fernet import Fernet

TIERS = ("fast", "balanced", "strong")

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = Fernet(self._secret("vault.key", Fernet.generate_key))
        self.token = self._secret("gateway.key", lambda: ("mr_" + secrets.token_urlsafe(32)).encode()).decode()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS providers (
                  id TEXT PRIMARY KEY, label TEXT NOT NULL, base TEXT NOT NULL,
                  model TEXT NOT NULL, tier TEXT NOT NULL, secret BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                  id TEXT PRIMARY KEY, started REAL, tier TEXT, reason TEXT, status TEXT,
                  duration_ms INTEGER, mode TEXT);
                CREATE TABLE IF NOT EXISTS attempts (
                  run_id TEXT, stage TEXT, provider TEXT, model TEXT, outcome TEXT,
                  duration_ms INTEGER, tokens INTEGER);
                CREATE TABLE IF NOT EXISTS provider_health (
                  provider_id TEXT PRIMARY KEY, state TEXT NOT NULL, detail TEXT NOT NULL,
                  http_status INTEGER, checked_at REAL NOT NULL, duration_ms INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS runs_started ON runs(started);
                CREATE INDEX IF NOT EXISTS attempts_run ON attempts(run_id);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(attempts)")}
            for column in ("input_tokens", "output_tokens"):
                if column not in columns:
                    db.execute("ALTER TABLE attempts ADD COLUMN " + column + " INTEGER")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY)")
            if not db.execute("SELECT 1 FROM settings WHERE key='seeded'").fetchone():
                db.execute("INSERT INTO providers VALUES(?,?,?,?,?,?)",
                           ("local","Local Ollama","http://127.0.0.1:11434/v1","llama3.1:latest","balanced",b""))
                db.execute("INSERT INTO settings VALUES('seeded')")

    def _secret(self, filename, factory):
        path = self.path / filename
        if not path.exists():
            with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as handle:
                handle.write(factory())
        return path.read_bytes()

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path / "relay.sqlite", timeout=15)) as conn:
            conn.row_factory = sqlite3.Row
            with conn:
                yield conn

    def providers(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("""
                SELECT p.*, h.state, h.detail, h.http_status, h.checked_at, h.duration_ms
                FROM providers p LEFT JOIN provider_health h ON h.provider_id = p.id ORDER BY p.rowid
            """)]

    def add(self, label, base, model, tier, key):
        provider_id = uuid.uuid4().hex
        secret = self.cipher.encrypt(key.encode()) if key else b""
        with self.db() as db:
            db.execute("INSERT INTO providers VALUES(?,?,?,?,?,?)", (provider_id,label,base,model,tier,secret))
        return {"id":provider_id,"label":label,"base":base,"model":model,"tier":tier,"secret":secret}

    def save_health(self, provider_id, result):
        with self.db() as db:
            db.execute("""INSERT OR REPLACE INTO provider_health
                SELECT id, :state, :detail, :http_status, :checked_at, :duration_ms
                FROM providers WHERE id=:id""", {"id":provider_id,**result})

    def remove(self, provider_id):
        with self.db() as db:
            db.execute("DELETE FROM provider_health WHERE provider_id=?", (provider_id,))
            return db.execute("DELETE FROM providers WHERE id=?", (provider_id,)).rowcount

    def register_local(self, name):
        base = "http://127.0.0.1:11434/v1"
        canonical = name if ":" in name else name + ":latest"
        with self.db() as db:
            db.execute("""INSERT INTO providers SELECT ?,?,?,?,?,?
                       WHERE NOT EXISTS (SELECT 1 FROM providers WHERE base=? AND model IN (?,?))""",
                       ("ollama:"+canonical, "Local Ollama", base, canonical, "balanced", b"",
                        base, canonical, name))

    def start(self, tier, reason, mode):
        run = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)",(run,time(),tier,reason,"running",0,mode))
        return run

    def attempt(self, run, stage, provider, outcome, duration, tokens, usage=None):
        usage = usage or {}
        def count(key):
            value = usage.get(key)
            return value if type(value) is int and 0 <= value <= 2**53 - 1 else None
        with self.db() as db:
            db.execute("""INSERT INTO attempts
                (run_id,stage,provider,model,outcome,duration_ms,tokens,input_tokens,output_tokens)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (run,stage,provider["label"],provider["model"],outcome,duration,
                 tokens if type(tokens) is int and 0 <= tokens <= 2**53 - 1 else None,
                 count("prompt_tokens"),count("completion_tokens")))

    def finish(self, run, status, duration):
        with self.db() as db:
            db.execute("UPDATE runs SET status=?, duration_ms=? WHERE id=?", (status,duration,run))

    def recent(self):
        with self.db() as db:
            rows = [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 50")]
            for r in rows:
                r["attempts"] = [dict(a) for a in db.execute(
                    "SELECT stage,provider,model,outcome,duration_ms,tokens FROM attempts WHERE run_id=? ORDER BY rowid",(r["id"],))]
        return rows
