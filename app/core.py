import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

DATA = Path(os.environ.get("SLIDECOACH_DATA", "data")).resolve()
DB = DATA / "slidecoach.sqlite3"
MODEL = os.environ.get("SLIDECOACH_MODEL", "")
MODEL_URL = os.environ.get("SLIDECOACH_MODEL_URL", "").rstrip("/")
PROVIDER = os.environ.get("SLIDECOACH_PROVIDER", "openai-compatible")


def model_configured():
    return bool(MODEL and MODEL_URL and (PROVIDER == "ollama" or os.environ.get("SLIDECOACH_API_KEY")))


def uid():
    return secrets.token_hex(16)


def now():
    return int(time.time())


def dump(obj):
    return json.dumps(obj, ensure_ascii=False)


@contextmanager
def db():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA / "uploads").mkdir(exist_ok=True, mode=0o700)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, password TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS auth(token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS courses(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, filename TEXT NOT NULL, kind TEXT NOT NULL, sha TEXT NOT NULL, created INTEGER NOT NULL, UNIQUE(user_id,sha));
        CREATE TABLE IF NOT EXISTS pages(course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE, number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, warning TEXT NOT NULL DEFAULT '', confirmed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(course_id,number));
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE, page_numbers TEXT NOT NULL, mode TEXT NOT NULL, level TEXT NOT NULL, minutes INTEGER NOT NULL, persist INTEGER NOT NULL, status TEXT NOT NULL, created INTEGER NOT NULL, updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, page_number INTEGER NOT NULL, mode TEXT NOT NULL, question TEXT NOT NULL, material TEXT NOT NULL, hints INTEGER NOT NULL DEFAULT 0, revealed INTEGER NOT NULL DEFAULT 0, source_opened INTEGER NOT NULL DEFAULT 0, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES turns(id) ON DELETE CASCADE, answer TEXT NOT NULL, feedback TEXT NOT NULL, independent INTEGER NOT NULL, disputed INTEGER NOT NULL DEFAULT 0, dispute_reason TEXT NOT NULL DEFAULT '', review TEXT, created INTEGER NOT NULL, request_key TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS operations(user_id TEXT NOT NULL, key TEXT NOT NULL, route TEXT NOT NULL, response TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(user_id,key,route));
        CREATE TABLE IF NOT EXISTS model_usage(at INTEGER NOT NULL, model TEXT NOT NULL, tokens INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS outlines(course_id TEXT PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE, fingerprint TEXT NOT NULL, data TEXT NOT NULL, created INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id,updated);
        CREATE INDEX IF NOT EXISTS idx_turns_session ON turns(session_id,created);
        ''')
        if "topic_plan" not in {r[1] for r in c.execute("PRAGMA table_info(sessions)")}:
            c.execute("ALTER TABLE sessions ADD COLUMN topic_plan TEXT NOT NULL DEFAULT '[]'")
        if "topic_id" not in {r[1] for r in c.execute("PRAGMA table_info(turns)")}:
            c.execute("ALTER TABLE turns ADD COLUMN topic_id TEXT NOT NULL DEFAULT ''")
        c.execute("DELETE FROM auth WHERE expires<?", (now(),))
        c.execute("DELETE FROM operations WHERE created<?", (now() - 86400,))
        # Temporary sessions are a bounded convenience, not indefinite history.
        c.execute("DELETE FROM sessions WHERE persist=0 AND updated<?", (now() - 86400,))


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + value


def clean_expired():
    with db() as c:
        c.execute("DELETE FROM sessions WHERE persist=0 AND updated<?", (now() - 86400,))
        c.execute("DELETE FROM operations WHERE created<?", (now() - 86400,))
        c.execute("DELETE FROM auth WHERE expires<?", (now(),))


def password_ok(password, encoded):
    return secrets.compare_digest(password_hash(password, encoded.split(":")[0]), encoded)


def compact(text):
    return re.sub(r"\s+", "", text).casefold()


def evidence_valid(quote, source):
    return len(compact(quote)) >= 8 and compact(quote) in compact(source)
