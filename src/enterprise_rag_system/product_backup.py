"""Read-only validation of a standalone registry snapshot, without schema migration."""

import sqlite3
from contextlib import closing
from pathlib import Path


def verify_backup(path: Path) -> dict:
    if not path.is_file():
        raise ValueError("Backup file does not exist")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Backup failed SQLite integrity check")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (1, 2):
            raise ValueError("Unsupported registry backup schema")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "versions", "heads", "generations", "audit"}.issubset(tables):
            raise ValueError("Missing registry tables")
        missing = db.execute("""SELECT count(*) FROM heads h LEFT JOIN versions v
            ON h.tenant=v.tenant AND h.doc_id=v.doc_id AND h.revision=v.revision
            WHERE v.doc_id IS NULL""").fetchone()[0]
        if missing:
            raise ValueError("Document heads reference missing versions")
        counts = {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("users", "versions", "heads")
        }
        return {
            "integrity": "ok",
            "schema_version": version,
            "counts": counts,
            "includes_original_uploads": False,
            "includes_qdrant_snapshot": False,
        }
