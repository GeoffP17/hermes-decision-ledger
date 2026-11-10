"""Read-only view of existing receipts. Never initialize, migrate or mutate storage."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from .core import Ledger, LedgerError


class ReceiptReader(Ledger):
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise LedgerError("ledger path must not be a symlink")

    @contextmanager
    def connect(self, write=False):
        if write:
            raise LedgerError("receipt reader is read-only")
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # One consistent read snapshot across count, proposals and events.
        try:
            schema = db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
            if not schema or schema[0] != '1':
                raise LedgerError("unsupported ledger schema")
            yield db
        finally:
            db.close()

    def page(self, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise LedgerError("invalid page")
        if not self.path.exists():
            return {"decisions": [], "total": 0, "next_offset": None}
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
            rows = db.execute("SELECT id FROM proposals ORDER BY created_at DESC,id LIMIT ? OFFSET ?", (limit, offset))
            items = [self._read(db, row[0]) for row in rows]
        # Only receipt content belongs on this page; don't expose saved conversation excerpts,
        # pending confirmation challenges, operator session IDs or commands through the API.
        records = [{k: item[k] for k in ('id', 'token', 'project', 'topic', 'scope', 'conditions', 'status', 'created_at', 'approval_basis', 'coverage')} |
                   {"events": [{"action": e['action'], "created_at": e['created_at']} for e in item['events']],
                    "source_attached": bool(item.get('evidence'))} for item in items]
        return {"decisions": records, "total": total,
                "next_offset": offset + limit if offset + limit < total else None}
