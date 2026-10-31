"""PSI capability grants: bounded delegation with expiry, revocation and audit.

Additive to original PSI QBrain9/Supabase branches. No automatic external
actions, credential downloads, or security decisions based on bond phrases.
A trusted application holds the high-entropy signing secret and issues grants;
agents may only present grants for the exact authorized task envelope.

This local SQLite backend is a development-stage authority prototype. It needs
separate production deployment, encrypted secret custody and identity binding.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

ACTION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,79}$")
GENESIS = "0" * 64


def stable(x: Any) -> str:
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class PSIPolicy:
    def __init__(self, db_path: str | Path, authority_key: bytes):
        if not isinstance(authority_key, bytes) or len(authority_key) < 32:
            raise ValueError("PSI requires at least 32 bytes of distinct authority key")
        self._key = authority_key
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA busy_timeout=30000")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS grants (
                grant_id TEXT PRIMARY KEY, subject TEXT NOT NULL,
                action TEXT NOT NULL, resource TEXT NOT NULL,
                expires_at REAL NOT NULL, max_uses INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0,
                issued_at REAL NOT NULL,
                token_digest TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_time REAL NOT NULL, action TEXT NOT NULL,
                grant_id TEXT NOT NULL, detail TEXT NOT NULL,
                previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "PSIPolicy":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _record(self, action: str, grant_id: str, detail: dict) -> None:
        prev = self.db.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        prior = prev[0] if prev else GENESIS
        now = time.time()
        core = {"event_time": now, "action": action, "grant_id": grant_id,
                "detail": detail, "previous_hash": prior}
        self.db.execute("INSERT INTO events(event_time,action,grant_id,detail,previous_hash,event_hash)"
                        " VALUES (?,?,?,?,?,?)", (now, action, grant_id, stable(detail),
                                                   prior, hashlib.sha256(stable(core).encode()).hexdigest()))

    def _token(self, grant_id: str) -> str:
        # An opaque bearer capability; only the grant ID is visible in logs.
        mac = hmac.new(self._key, ("PSI-GRANT-v1:" + grant_id).encode(), hashlib.sha256)
        return grant_id + "." + mac.hexdigest()

    def issue(self, *, subject: str, action: str, resource: str,
              duration_seconds: int = 3600, max_uses: int = 1) -> str:
        """Trusted operator/controller only. Never expose through public API."""
        if not isinstance(subject, str) or not 1 <= len(subject) <= 128 or not subject.strip():
            raise ValueError("subject required")
        if not isinstance(resource, str) or not 1 <= len(resource) <= 256 or not resource.strip():
            raise ValueError("resource required")
        if not isinstance(action, str) or not ACTION_RE.fullmatch(action):
            raise ValueError("invalid exact action name")
        if type(duration_seconds) is not int or not 1 <= duration_seconds <= 86400:
            raise ValueError("duration_seconds must be 1..86400")
        if type(max_uses) is not int or not 1 <= max_uses <= 10_000:
            raise ValueError("max_uses must be 1..10000")
        grant_id = secrets.token_hex(16)
        token = self._token(grant_id)
        token_digest = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "INSERT INTO grants(grant_id,subject,action,resource,expires_at,max_uses,"
                "issued_at,token_digest) VALUES(?,?,?,?,?,?,?,?)",
                (grant_id, subject, action, resource, now + duration_seconds,
                 max_uses, now, token_digest),
            )
            self._record("issued", grant_id, {
                "subject": subject, "action": action, "resource": resource,
                "expires_at": now + duration_seconds, "max_uses": max_uses,
            })
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return token

    def revoke(self, grant_id: str) -> bool:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute("UPDATE grants SET revoked=1 WHERE grant_id=? AND revoked=0",
                                  (grant_id,))
            if cur.rowcount:
                self._record("revoked", grant_id, {})
            self.db.execute("COMMIT")
            return bool(cur.rowcount)
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def authorize(self, token: str, *, subject: str, action: str,
                  resource: str, use: bool = True) -> bool:
        """Fail-closed exact-match decision; successful use consumes quota."""
        if not isinstance(token, str) or len(token) != 97 or "." not in token:
            return False
        grant_id, sep, mac = token.partition(".")
        if not re.fullmatch(r"[0-9a-f]{32}", grant_id) or not re.fullmatch(r"[0-9a-f]{64}", mac):
            return False
        if not hmac.compare_digest(token, self._token(grant_id)):
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
            allowed = bool(
                row and hmac.compare_digest(row["token_digest"], hashlib.sha256(token.encode()).hexdigest())
                and row["subject"] == subject and row["action"] == action
                and row["resource"] == resource and row["revoked"] == 0
                and row["expires_at"] > time.time()
                and row["used"] < row["max_uses"]
            )
            if allowed and use:
                self.db.execute("UPDATE grants SET used=used+1 WHERE grant_id=?", (grant_id,))
                self._record("used", grant_id, {
                    "subject": subject, "action": action, "resource": resource,
                })
            # A failed attempt with a valid token ID does not reveal identity or token.
            if not allowed:
                self._record("denied", grant_id, {"reason": "outside-grant"})
            self.db.execute("COMMIT")
            return allowed
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self) -> dict[str, Any]:
        prior = GENESIS
        checked = 0
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            core = {"event_time": row["event_time"], "action": row["action"],
                    "grant_id": row["grant_id"], "detail": json.loads(row["detail"]),
                    "previous_hash": row["previous_hash"]}
            expected = hashlib.sha256(stable(core).encode()).hexdigest()
            if row["previous_hash"] != prior or not hmac.compare_digest(row["event_hash"], expected):
                return {"ok": False, "checked": checked, "bad_seq": row["seq"]}
            prior = row["event_hash"]
            checked += 1
        return {"ok": True, "checked": checked, "tip": prior}
