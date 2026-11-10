"""Small transactional ledger. Interpretation is never promoted by model tool calls.

The local process and filesystem are trusted. Hashes detect accidental changes; they
are not signatures and do not defend against another process that can edit SQLite.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class LedgerError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def text(value, name, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LedgerError(f"{name} must be nonempty text, at most {limit} characters")
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise LedgerError(f"{name} contains control characters")
    return value.strip()


def key(value, name):
    value = text(value, name, 100)
    if not all(c.isascii() and (c.isalnum() or c in "-_.") for c in value):
        raise LedgerError(f"{name} must contain only ASCII letters, numbers, -, _ or .")
    return value.lower()


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Do not follow an existing symlink; this is hygiene, not hostile-host isolation.
        if self.path.is_symlink():
            raise LedgerError("ledger path must not be a symlink")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        if os.name == "posix":
            os.chmod(self.path, 0o600)
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              INSERT OR IGNORE INTO metadata VALUES ('schema', '1');
              CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY, project TEXT NOT NULL, topic TEXT NOT NULL,
                payload TEXT NOT NULL, digest TEXT NOT NULL, created_at TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT NOT NULL,
                action TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(proposal_id) REFERENCES proposals(id));
              CREATE TABLE IF NOT EXISTS pending_reviews (
                nonce TEXT PRIMARY KEY, proposal_id TEXT NOT NULL,
                token TEXT NOT NULL, action TEXT NOT NULL,
                session_id TEXT NOT NULL, command TEXT NOT NULL,
                replace_token TEXT, note TEXT, preview_digest TEXT NOT NULL,
                event_revision INTEGER NOT NULL, expires_at INTEGER NOT NULL,
                FOREIGN KEY(proposal_id) REFERENCES proposals(id));
            """)
            if db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()[0] != "1":
                raise LedgerError("unsupported ledger schema; refusing to guess")

    @contextmanager
    def connect(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def draft(self, project, topic, scope, conditions=None, evidence=None):
        project, topic = key(project, "project"), key(topic, "topic")
        scope = text(scope, "scope")
        if conditions is None:
            conditions = []
        if not isinstance(conditions, list) or len(conditions) > 12:
            raise LedgerError("conditions must be a list with at most 12 entries")
        conditions = [text(c, "condition", 1000) for c in conditions]
        if evidence is not None:
            # The adapter supplies the snapshot, never a model's asserted quote.
            if not isinstance(evidence, dict) or not all(k in evidence for k in ("session_id", "message_id", "messages", "digest")):
                raise LedgerError("invalid evidence snapshot")
            if digest(evidence["messages"]) != evidence["digest"]:
                raise LedgerError("evidence digest mismatch")
        payload = {"project": project, "topic": topic, "scope": scope,
                   "conditions": conditions, "evidence": evidence}
        checksum = digest(payload)
        with self.connect(write=True) as db:
            old = db.execute("SELECT id FROM proposals WHERE project=? AND topic=? AND digest=? ORDER BY rowid DESC LIMIT 1",
                             (project, topic, checksum)).fetchone()
            if old:
                existing = self._read(db, old["id"])
                if existing["status"] in {"proposed", "approved", "conditional"}:
                    return existing
                # A genuinely NEW proposal may re-request an unchanged revoked scope.
                # It receives a new id and requires a new explicit command; replay
                # of the old command still addresses only the terminal old receipt.
            pid = uuid.uuid4().hex[:12]
            db.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?)",
                       (pid, project, topic, canonical(payload), checksum, now()))
            return self._read(db, pid)

    def _read(self, db, pid):
        r = db.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        if not r:
            raise LedgerError("unknown decision id")
        payload = json.loads(r["payload"])
        if digest(payload) != r["digest"]:
            raise LedgerError("proposal integrity check failed")
        events = [dict(e) for e in db.execute("SELECT * FROM events WHERE proposal_id=? ORDER BY seq", (pid,))]
        for e in events:
            e["data"] = json.loads(e["data"])
        action = events[-1]["action"] if events else "proposed"
        status = {"approve": "conditional" if payload["conditions"] else "approved",
                  "satisfy": "approved", "reject": "rejected", "revoke": "revoked",
                  "supersede": "superseded", "proposed": "proposed"}[action]
        return {"id": pid, "token": f"{pid}:{r['digest'][:16]}",
                **payload, "status": status, "created_at": r["created_at"],
                "events": events, "record_basis": "local operator command" if events else "assistant draft",
                "approval_basis": "operator receipt; see current status" if any(e["action"] == "approve" for e in events) else "not established",
                "coverage": "registered decisions only; missing records do not establish absence of approval"}

    def get(self, pid):
        with self.connect() as db:
            return self._read(db, pid)

    def list(self, project=None, topic=None, offset=0, limit=50):
        if project is not None:
            project = key(project, "project")
        if topic is not None:
            topic = key(topic, "topic")
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise LedgerError("offset must be nonnegative; limit must be 1..100")
        with self.connect() as db:
            args, parts = [], []
            for col, value in (("project", project), ("topic", topic)):
                if value is not None:
                    parts.append(col + "=?")
                    args.append(value)
            where = " WHERE " + " AND ".join(parts) if parts else ""
            total = db.execute("SELECT COUNT(*) FROM proposals" + where, args).fetchone()[0]
            rows = db.execute("SELECT id FROM proposals" + where + " ORDER BY created_at,id LIMIT ? OFFSET ?",
                              args + [limit, offset]).fetchall()
            return {"decisions": [self._read(db, r[0]) for r in rows], "total": total,
                    "next_offset": offset + limit if offset + limit < total else None,
                    "coverage": "registered decisions only; historical completeness unknown",
                    "scope_matching": "exact project/topic keys; semantic overlap across keys is not resolved"}

    def _token(self, db, token):
        if not isinstance(token, str) or token.count(":") != 1:
            raise LedgerError("use the exact id:digest token shown on the decision card")
        pid, _ = token.split(":")
        result = self._read(db, pid)
        if token != result["token"]:
            raise LedgerError("stale or incorrect decision token")
        return result

    def transition(self, token, action, *, session_id, command, replace=None, note=None):
        """Trusted operator surface only. Deliberately not registered as a model tool."""
        if action not in {"approve", "reject", "revoke", "satisfy"}:
            raise LedgerError("unsupported transition")
        session_id = text(session_id, "operator session", 300)
        command = text(command, "operator command", 8000)
        if action == "satisfy" and not note:
            raise LedgerError("satisfy requires the operator's evidence note for all listed conditions")
        if note is not None:
            note = text(note, "note", 2000)
        with self.connect(write=True) as db:
            return self._transition_in_tx(db, token, action, session_id=session_id,
                                          command=command, replace=replace, note=note)

    def _transition_in_tx(self, db, token, action, *, session_id, command, replace=None, note=None):
        item = self._token(db, token)
        state = item["status"]
        # An identical completed request is a no-op; replay never restores a revoked approval.
        last = item["events"][-1] if item["events"] else None
        if last and last["action"] == action and last["data"]["command"] == command:
            return item
        allowed = {"approve": {"proposed"}, "reject": {"proposed"},
                   "revoke": {"approved", "conditional"}, "satisfy": {"conditional"}}
        if state not in allowed[action]:
            raise LedgerError(f"cannot {action} a {state} decision; draft a new exact scope instead")
        if replace and action != "approve":
            raise LedgerError("replace is valid only with approve")
        if action == "approve":
            siblings = db.execute("SELECT id FROM proposals WHERE project=? AND topic=? AND id<>?",
                                  (item["project"], item["topic"], item["id"])).fetchall()
            live = [self._read(db, r[0]) for r in siblings]
            live = [r for r in live if r["status"] in {"approved", "conditional"}]
            if live and (not replace or len(live) != 1 or live[0]["token"] != replace):
                raise LedgerError("an approved decision exists for this topic; use approve NEW replace OLD explicitly")
            if replace and (not live or live[0]["token"] != replace):
                raise LedgerError("replacement must identify the current approved decision in the same topic")
        data = {"session_id": session_id, "command": command,
                "actor": "local_operator", "note": note, "replaces": replace}
        if replace:
            old = self._token(db, replace)
            db.execute("INSERT INTO events(proposal_id,action,data,created_at) VALUES (?,?,?,?)",
                       (old["id"], "supersede", canonical({**data, "replaced_by": token}), now()))
        db.execute("INSERT INTO events(proposal_id,action,data,created_at) VALUES (?,?,?,?)",
                   (item["id"], action, canonical(data), now()))
        return self._read(db, item["id"])


    # Confirmation challenges are persisted so a real Hermes CLI invocation can
    # preview in one process and commit in a later process. They are not security
    # tokens against same-UID Python/filesystem access (see README threat model).
    def prepare_review(self, token, action, *, session_id, command, preview, replace=None, note=None):
        if action not in {"approve", "reject", "revoke", "satisfy"}:
            raise LedgerError("unsupported review action")
        session_id = text(session_id, "operator session", 300)
        command = text(command, "operator command", 8000)
        if action == "satisfy" and not note:
            raise LedgerError("satisfy requires the operator's evidence note for all listed conditions")
        if note is not None:
            note = text(note, "note", 2000)
        if replace and action != "approve":
            raise LedgerError("replace is valid only with approve")
        token = text(token, "decision token", 100)
        with self.connect(write=True) as db:
            item = self._token(db, token)
            allowed = {"approve": {"proposed"}, "reject": {"proposed"},
                       "revoke": {"approved", "conditional"}, "satisfy": {"conditional"}}
            if item["status"] not in allowed[action]:
                raise LedgerError(f"cannot {action} a {item['status']} decision; draft a new exact scope instead")
            if action == "approve":
                siblings = db.execute("SELECT id FROM proposals WHERE project=? AND topic=? AND id<>?",
                                      (item["project"], item["topic"], item["id"])).fetchall()
                live = [self._read(db, row[0]) for row in siblings]
                live = [other for other in live if other["status"] in {"approved", "conditional"}]
                if live and (not replace or len(live) != 1 or live[0]["token"] != replace):
                    raise LedgerError("an approved decision exists for this topic; use approve NEW replace OLD explicitly")
                if replace and (len(live) != 1 or live[0]["token"] != replace):
                    raise LedgerError("replacement must identify the current approved decision in the same topic")
            revision = db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]
            nonce = secrets.token_urlsafe(24)
            epoch = int(time.time())
            # An operator session may have only one pending review. Old challenges
            # are deleted, not turned into ledger events.
            db.execute("DELETE FROM pending_reviews WHERE session_id=? OR expires_at<?", (session_id, epoch))
            db.execute("""INSERT INTO pending_reviews
                      (nonce, proposal_id, token, action, session_id, command,
                       replace_token, note, preview_digest, event_revision, expires_at)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (nonce, item["id"], token, action, session_id, command,
                        replace, note, digest(preview), revision, epoch + 900))
            return nonce

    def get_pending_review(self, nonce, session_id):
        nonce = text(nonce, "confirmation code", 120)
        with self.connect() as db:
            row = db.execute("SELECT * FROM pending_reviews WHERE nonce=?", (nonce,)).fetchone()
            if not row or row["session_id"] != session_id or row["expires_at"] < time.time():
                raise LedgerError("confirmation is missing, expired, or belongs to another operator session; preview again")
            return dict(row)

    def cancel_review(self, nonce, session_id):
        with self.connect(write=True) as db:
            deleted = db.execute("DELETE FROM pending_reviews WHERE nonce=? AND session_id=?", (nonce, session_id))
            return deleted.rowcount == 1

    def confirm_review(self, nonce, session_id, preview):
        """Validate and consume challenge + transition in ONE SQLite transaction."""
        session_id = text(session_id, "operator session", 300)
        with self.connect(write=True) as db:
            row = db.execute("SELECT * FROM pending_reviews WHERE nonce=?", (nonce,)).fetchone()
            if not row or row["session_id"] != session_id or row["expires_at"] < time.time():
                raise LedgerError("confirmation is missing, expired, or belongs to another operator session; preview again")
            if row["preview_digest"] != digest(preview):
                raise LedgerError("decision preview or source verification changed; preview again before confirming")
            if row["event_revision"] != db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0]:
                raise LedgerError("ledger changed after preview; preview again before confirming")
            result = self._transition_in_tx(db, row["token"], row["action"],
                     session_id=session_id, command=row["command"] + " -> confirmed " + nonce,
                     replace=row["replace_token"], note=row["note"])
            db.execute("DELETE FROM pending_reviews WHERE nonce=?", (nonce,))
            return result
