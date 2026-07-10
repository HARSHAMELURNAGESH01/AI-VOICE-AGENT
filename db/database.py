"""
db/database.py

SQLite storage: zero-setup, single file, reviewers can run it anywhere.
Tables: callers, viewings, opt_outs, conversations.

The conversations table is a tamper-evident audit log: each record stores
a SHA-256 hash of (previous record's hash + this record's canonical JSON).
Altering any historical record breaks the chain, which verify_audit_chain()
detects. Compliance isn't just following rules -- it's being able to PROVE
you did, later.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "lena.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS callers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE,
    name TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS viewings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    caller_phone TEXT,
    caller_name TEXT,
    unit_id TEXT,
    slot TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS opt_outs (
    phone TEXT PRIMARY KEY,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS sms_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    to_phone TEXT,
    body TEXT,
    status TEXT,
    mode TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    transcript_json TEXT,
    triggers_json TEXT,
    guardrail_events_json TEXT,
    qa_scorecard_json TEXT,
    summary_json TEXT,
    cost_json TEXT,
    created_at TEXT,
    prev_hash TEXT,
    record_hash TEXT
);
"""


class Database:
    def __init__(self, path: Path | None = None):
        self.conn = sqlite3.connect(path or DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        # Migration for databases created before the summary feature
        try:
            self.conn.execute("ALTER TABLE conversations ADD COLUMN summary_json TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        self.conn.commit()

    # ------------------------------------------------------------ callers
    def get_or_create_caller(self, phone: str, name: str | None = None) -> dict:
        cur = self.conn.execute("SELECT * FROM callers WHERE phone=?", (phone,))
        row = cur.fetchone()
        if row:
            if name and not row["name"]:
                self.conn.execute("UPDATE callers SET name=? WHERE phone=?", (name, phone))
                self.conn.commit()
            return dict(row)
        self.conn.execute(
            "INSERT INTO callers (phone, name, created_at) VALUES (?,?,?)",
            (phone, name, _now()),
        )
        self.conn.commit()
        return {"phone": phone, "name": name}

    # ----------------------------------------------------------- viewings
    def book_viewing(self, caller_phone: str, caller_name: str, unit_id: str, slot: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO viewings (caller_phone, caller_name, unit_id, slot, created_at) VALUES (?,?,?,?,?)",
            (caller_phone, caller_name, unit_id, slot, _now()),
        )
        self.conn.commit()
        return cur.lastrowid

    # ----------------------------------------------------------- opt outs
    def log_opt_out(self, phone: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO opt_outs (phone, created_at) VALUES (?,?)",
            (phone, _now()),
        )
        self.conn.commit()

    def is_opted_out(self, phone: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM opt_outs WHERE phone=?", (phone,))
        return cur.fetchone() is not None

    # ----------------------------------------- tamper-evident conversations
    def save_conversation(self, conversation_id: str, transcript: list,
                          triggers: list, guardrail_events: list,
                          qa_scorecard: dict | None, cost: dict,
                          summary: dict | None = None) -> str:
        prev_hash = self._latest_hash()
        record = {
            "conversation_id": conversation_id,
            "transcript": transcript,
            "triggers": triggers,
            "guardrail_events": guardrail_events,
            "qa_scorecard": qa_scorecard,
            "summary": summary,
            "cost": cost,
            "created_at": _now(),
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256((prev_hash + canonical).encode()).hexdigest()
        self.conn.execute(
            """INSERT INTO conversations
               (conversation_id, transcript_json, triggers_json,
                guardrail_events_json, qa_scorecard_json, summary_json, cost_json,
                created_at, prev_hash, record_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (conversation_id, json.dumps(transcript), json.dumps(triggers),
             json.dumps(guardrail_events),
             json.dumps(qa_scorecard) if qa_scorecard else None,
             json.dumps(summary) if summary else None,
             json.dumps(cost), record["created_at"], prev_hash, record_hash),
        )
        self.conn.commit()
        return record_hash

    def _latest_hash(self) -> str:
        cur = self.conn.execute(
            "SELECT record_hash FROM conversations ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row["record_hash"] if row else "GENESIS"

    def verify_audit_chain(self) -> tuple[bool, int]:
        """Recompute every hash. Returns (chain_valid, records_checked)."""
        cur = self.conn.execute("SELECT * FROM conversations ORDER BY id ASC")
        prev_hash = "GENESIS"
        checked = 0
        for row in cur.fetchall():
            record = {
                "conversation_id": row["conversation_id"],
                "transcript": json.loads(row["transcript_json"]),
                "triggers": json.loads(row["triggers_json"]),
                "guardrail_events": json.loads(row["guardrail_events_json"]),
                "qa_scorecard": json.loads(row["qa_scorecard_json"]) if row["qa_scorecard_json"] else None,
                "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
                "cost": json.loads(row["cost_json"]),
                "created_at": row["created_at"],
            }
            canonical = json.dumps(record, sort_keys=True, separators=(",", ":"))
            expected = hashlib.sha256((prev_hash + canonical).encode()).hexdigest()
            if expected != row["record_hash"] or row["prev_hash"] != prev_hash:
                return False, checked
            prev_hash = row["record_hash"]
            checked += 1
        return True, checked



    # ---------------------------------------------------------- sms log
    def log_sms(self, conversation_id: str, to: str, body: str,
                status: str, mode: str) -> None:
        self.conn.execute(
            "INSERT INTO sms_log (conversation_id, to_phone, body, status, mode, created_at) VALUES (?,?,?,?,?,?)",
            (conversation_id, to, body, status, mode, _now()),
        )
        self.conn.commit()

    def list_sms(self, conversation_id: str) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM sms_log WHERE conversation_id=? ORDER BY id", (conversation_id,)
        )
        return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------- dashboard queries
    def list_conversations(self, limit: int = 100) -> list[dict]:
        cur = self.conn.execute(
            "SELECT * FROM conversations ORDER BY id DESC LIMIT ?", (limit,)
        )
        out = []
        for row in cur.fetchall():
            out.append({
                "id": row["id"],
                "conversation_id": row["conversation_id"],
                "created_at": row["created_at"],
                "transcript": json.loads(row["transcript_json"]),
                "triggers": json.loads(row["triggers_json"]),
                "guardrail_events": json.loads(row["guardrail_events_json"]),
                "qa_scorecard": json.loads(row["qa_scorecard_json"]) if row["qa_scorecard_json"] else None,
                "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
                "cost": json.loads(row["cost_json"]),
                "record_hash": row["record_hash"],
                "sms": self.list_sms(row["conversation_id"]),
            })
        return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
