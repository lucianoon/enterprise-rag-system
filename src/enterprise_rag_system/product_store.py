"""Transactional pilot registry. Every operation is scoped to a token's tenant."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoreError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    visibility: Literal["private", "tenant"] = "private"
    readers: list[str] = Field(default_factory=list, max_length=100)
    expected_revision: int = Field(ge=0)

    @field_validator("title", "text")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Blank content is not allowed")
        return value


@dataclass(frozen=True)
class Principal:
    tenant: str
    user: str
    role: str


class Registry:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if (
                version == 0
                and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' LIMIT 1"
                ).fetchone()
            ):
                raise ValueError("Database is not an empty registry")
            if version not in (0, 1, 2):
                raise ValueError("Unsupported registry schema; do not downgrade this database")
            schema = """
                CREATE TABLE IF NOT EXISTS users (
                    tenant TEXT NOT NULL, user TEXT NOT NULL, role TEXT NOT NULL,
                    token_hash TEXT UNIQUE, PRIMARY KEY(tenant,user));
                CREATE TABLE IF NOT EXISTS versions (
                    tenant TEXT NOT NULL, doc_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    title TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL,
                    readers TEXT NOT NULL, owner TEXT NOT NULL, deleted INTEGER NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(tenant,doc_id,revision));
                CREATE TABLE IF NOT EXISTS heads (
                    tenant TEXT NOT NULL, doc_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(tenant,doc_id));
                CREATE TABLE IF NOT EXISTS generations (
                    tenant TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, user TEXT NOT NULL,
                    action TEXT NOT NULL, resource TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mutations (
                    tenant TEXT NOT NULL, user TEXT NOT NULL, window INTEGER NOT NULL,
                    count INTEGER NOT NULL, PRIMARY KEY(tenant,user,window));
                CREATE TABLE IF NOT EXISTS usage (
                    tenant TEXT NOT NULL, user TEXT NOT NULL, window INTEGER NOT NULL,
                    count INTEGER NOT NULL, PRIMARY KEY(tenant,user,window));
                CREATE TABLE IF NOT EXISTS query_events (
                    id TEXT PRIMARY KEY, tenant TEXT NOT NULL, user TEXT NOT NULL,
                    created REAL NOT NULL, corpus_revision INTEGER NOT NULL,
                    generation_mode TEXT NOT NULL, latency_ms REAL NOT NULL,
                    citation_count INTEGER NOT NULL,
                    rating TEXT, reason TEXT);
                CREATE INDEX IF NOT EXISTS query_events_tenant_created
                    ON query_events(tenant,created DESC,id DESC);
                PRAGMA user_version=2;
            """
            for statement in schema.split(";"):
                if statement.strip():
                    db.execute(statement)
        with closing(sqlite3.connect(path, timeout=5)) as db:
            db.execute("PRAGMA journal_mode=WAL")
        path.chmod(0o600)

    @contextmanager
    def connection(self, *, write: bool = False):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=5000")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _principal(db, token: str) -> Principal:
        if not token or len(token) > 256:
            raise StoreError(401, "Invalid credential")
        row = db.execute(
            "SELECT tenant,user,role FROM users WHERE token_hash=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
        if row is None:
            raise StoreError(401, "Invalid credential")
        return Principal(row["tenant"], row["user"], row["role"])

    @staticmethod
    def _audit(db, principal: Principal, action: str, resource: str = "") -> None:
        db.execute(
            "INSERT INTO audit(tenant,user,action,resource,created) VALUES(?,?,?,?,?)",
            (principal.tenant, principal.user, action, resource, time()),
        )

    def issue_user(self, tenant: str, user: str, role: str) -> str:
        """Operator-only provisioning/rotation; never exposed as an anonymous route."""
        if not tenant.strip() or not user.strip() or role not in ("admin", "editor", "reader"):
            raise ValueError("Specify tenant, user and admin/editor/reader role")
        token = secrets.token_urlsafe(32)
        with self.connection(write=True) as db:
            db.execute(
                "INSERT INTO users VALUES(?,?,?,?) ON CONFLICT(tenant,user) DO UPDATE "
                "SET role=excluded.role,token_hash=excluded.token_hash",
                (tenant, user, role, hashlib.sha256(token.encode()).hexdigest()),
            )
            self._audit(db, Principal(tenant, user, role), "credential_rotated")
        return token

    def revoke(self, tenant: str, user: str) -> None:
        with self.connection(write=True) as db:
            db.execute("UPDATE users SET token_hash=NULL WHERE tenant=? AND user=?", (tenant, user))
            self._audit(db, Principal(tenant, user, ""), "credential_revoked")

    @staticmethod
    def _readable(row, principal: Principal) -> bool:
        return (
            principal.role == "admin"
            or row["owner"] == principal.user
            or row["visibility"] == "tenant"
            or principal.user in json.loads(row["readers"])
        )

    @staticmethod
    def _heads(db, tenant: str):
        return db.execute(
            "SELECT v.* FROM versions v JOIN heads h ON "
            "v.tenant=h.tenant AND v.doc_id=h.doc_id AND v.revision=h.revision "
            "WHERE h.tenant=? ORDER BY v.doc_id",
            (tenant,),
        ).fetchall()

    def documents(self, token: str, *, consume_query: bool = False, include_deleted: bool = False):
        # Auth, permission snapshot and generation are read in one transaction.
        with self.connection(write=consume_query) as db:
            principal = self._principal(db, token)
            if include_deleted and principal.role != "admin":
                raise StoreError(403, "Admin permission required for deleted documents")
            if consume_query:
                window = int(time() // 60)
                db.execute("DELETE FROM usage WHERE window < ?", (window - 1,))
                db.execute(
                    "INSERT INTO usage VALUES(?,?,?,1) ON CONFLICT(tenant,user,window) "
                    "DO UPDATE SET count=count+1",
                    (principal.tenant, principal.user, window),
                )
                count = db.execute(
                    "SELECT count FROM usage WHERE tenant=? AND user=? AND window=?",
                    (principal.tenant, principal.user, window),
                ).fetchone()[0]
                if count > 30:
                    raise StoreError(429, "Query limit reached; retry next minute")
                self._audit(db, principal, "query")
            rows = [
                dict(r)
                for r in self._heads(db, principal.tenant)
                if (not r["deleted"] or include_deleted) and self._readable(r, principal)
            ]
            version = db.execute(
                "SELECT revision FROM generations WHERE tenant=?", (principal.tenant,)
            ).fetchone()
            return principal, version[0] if version else 0, rows

    @staticmethod
    def _mutation_limit(db, p: Principal):
        window = int(time() // 60)
        db.execute("DELETE FROM mutations WHERE window < ?", (window - 1,))
        db.execute(
            "INSERT INTO mutations VALUES(?,?,?,1) ON CONFLICT(tenant,user,window) "
            "DO UPDATE SET count=count+1",
            (p.tenant, p.user, window),
        )
        count = db.execute(
            "SELECT count FROM mutations WHERE tenant=? AND user=? AND window=?",
            (p.tenant, p.user, window),
        ).fetchone()[0]
        if count > 20:
            raise StoreError(429, "Write limit reached; retry next minute")

    def write_document(self, token: str, doc_id: str, document: DocumentInput):
        with self.connection(write=True) as db:
            principal = self._principal(db, token)
            if principal.role not in ("admin", "editor"):
                raise StoreError(403, "Editor permission required")
            self._mutation_limit(db, principal)
            rows = self._heads(db, principal.tenant)
            previous = next((r for r in rows if r["doc_id"] == doc_id), None)
            if previous is not None and not self._readable(previous, principal):
                raise StoreError(404, "Document not found")
            revision = previous["revision"] if previous else 0
            if revision != document.expected_revision:
                raise StoreError(409, "Document revision changed; reload before saving")
            if (previous is None or previous["deleted"]) and sum(
                not r["deleted"] for r in rows
            ) >= 200:
                raise StoreError(409, "Pilot limit: 200 active documents per tenant")
            for user in document.readers:
                if not db.execute(
                    "SELECT 1 FROM users WHERE tenant=? AND user=?", (principal.tenant, user)
                ).fetchone():
                    raise StoreError(422, "Reader must belong to this tenant")
            revision += 1
            db.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    principal.tenant,
                    doc_id,
                    revision,
                    document.title,
                    document.text,
                    document.visibility,
                    json.dumps(sorted(set(document.readers))),
                    previous["owner"] if previous else principal.user,
                    0,
                    time(),
                ),
            )
            self._publish(db, principal, doc_id, revision, "document_saved")
            return {"doc_id": doc_id, "revision": revision}

    @classmethod
    def _publish(cls, db, principal: Principal, doc_id: str, revision: int, action: str):
        db.execute(
            "INSERT INTO heads VALUES(?,?,?) ON CONFLICT(tenant,doc_id) DO UPDATE "
            "SET revision=excluded.revision",
            (principal.tenant, doc_id, revision),
        )
        db.execute(
            "INSERT INTO generations VALUES(?,1) ON CONFLICT(tenant) DO UPDATE "
            "SET revision=revision+1",
            (principal.tenant,),
        )
        cls._audit(db, principal, action, doc_id)

    def delete_document(self, token: str, doc_id: str, expected_revision: int):
        with self.connection(write=True) as db:
            p = self._principal(db, token)
            if p.role not in ("admin", "editor"):
                raise StoreError(403, "Editor permission required")
            row = next((r for r in self._heads(db, p.tenant) if r["doc_id"] == doc_id), None)
            if row is None or row["deleted"] or not self._readable(row, p):
                raise StoreError(404, "Document not found")
            if row["revision"] != expected_revision:
                raise StoreError(409, "Document revision changed; reload before deleting")
            self._mutation_limit(db, p)
            revision = row["revision"] + 1
            db.execute(
                "INSERT INTO versions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    p.tenant,
                    doc_id,
                    revision,
                    row["title"],
                    "",
                    row["visibility"],
                    row["readers"],
                    row["owner"],
                    1,
                    time(),
                ),
            )
            self._publish(db, p, doc_id, revision, "document_deleted")
            return {"doc_id": doc_id, "revision": revision}

    def history(self, token: str, doc_id: str):
        with self.connection() as db:
            p = self._principal(db, token)
            if p.role != "admin":
                raise StoreError(403, "Admin permission required for history")
            return [
                dict(r)
                for r in db.execute(
                    "SELECT revision,title,deleted,created FROM versions "
                    "WHERE tenant=? AND doc_id=? ORDER BY revision DESC LIMIT 100",
                    (p.tenant, doc_id),
                )
            ]

    def audit(self, token: str):
        with self.connection() as db:
            p = self._principal(db, token)
            if p.role != "admin":
                raise StoreError(403, "Admin permission required")
            return [
                dict(r)
                for r in db.execute(
                    "SELECT user,action,resource,created FROM audit WHERE tenant=? "
                    "ORDER BY id DESC LIMIT 100",
                    (p.tenant,),
                )
            ]

    def restore(self, token: str, doc_id: str, revision: int, expected_revision: int):
        with self.connection() as db:
            p = self._principal(db, token)
            if p.role != "admin":
                raise StoreError(403, "Admin permission required")
            current = next((r for r in self._heads(db, p.tenant) if r["doc_id"] == doc_id), None)
            old = db.execute(
                "SELECT title,text,deleted FROM versions "
                "WHERE tenant=? AND doc_id=? AND revision=?",
                (p.tenant, doc_id, revision),
            ).fetchone()
            if old is None or current is None:
                raise StoreError(404, "Document version not found")
            if current["revision"] != expected_revision:
                raise StoreError(409, "Document revision changed; reload before restoring")
            if old["deleted"]:
                raise StoreError(422, "Select a content version, not a deletion marker")
            # Restoring old text must not silently restore obsolete access grants.
            value = DocumentInput(
                title=old["title"],
                text=old["text"],
                visibility=current["visibility"],
                readers=json.loads(current["readers"]),
                expected_revision=expected_revision,
            )
        return self.write_document(token, doc_id, value)

    def backup(self, destination: Path):
        """Consistent SQLite backup, including WAL; never overwrite an existing file."""
        import os

        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            with (
                closing(sqlite3.connect(self.path)) as source,
                closing(sqlite3.connect(destination)) as target,
            ):
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError("Backup failed SQLite integrity check")
        except Exception:
            destination.unlink()
            raise

    @staticmethod
    def _prune_measurements(db, tenant: str, now: float):
        db.execute(
            "DELETE FROM query_events WHERE tenant=? AND created < ?", (tenant, now - 30 * 86400)
        )
        db.execute(
            "DELETE FROM query_events WHERE tenant=? AND id IN "
            "(SELECT id FROM query_events WHERE tenant=? "
            "ORDER BY created DESC,id DESC LIMIT -1 OFFSET 10000)",
            (tenant, tenant),
        )

    def record_query(
        self, token: str, revision: int, mode: str, latency_ms: float, citation_count: int
    ) -> str:
        # No prompt, answer, document ID or title enters the measurement ledger.
        query_id = secrets.token_hex(16)
        with self.connection(write=True) as db:
            p = self._principal(db, token)
            now = time()
            db.execute(
                "INSERT INTO query_events VALUES(?,?,?,?,?,?,?,?,NULL,NULL)",
                (query_id, p.tenant, p.user, now, revision, mode, latency_ms, citation_count),
            )
            self._prune_measurements(db, p.tenant, now)
        return query_id

    def feedback(self, token: str, query_id: str, rating: str, reason: str | None):
        with self.connection(write=True) as db:
            p = self._principal(db, token)
            row = db.execute(
                "SELECT rating,reason FROM query_events WHERE id=? AND tenant=? AND user=? "
                "AND created>=?",
                (query_id, p.tenant, p.user, time() - 30 * 86400),
            ).fetchone()
            if row is None:
                raise StoreError(404, "Query not found or feedback window expired")
            if (row["rating"], row["reason"]) != (rating, reason):
                self._mutation_limit(db, p)
                db.execute(
                    "UPDATE query_events SET rating=?,reason=? WHERE id=?",
                    (rating, reason, query_id),
                )
            return {"query_id": query_id, "rating": rating, "reason": reason}

    def quality(self, token: str, days: int = 30):
        with self.connection() as db:
            p = self._principal(db, token)
            if p.role != "admin":
                raise StoreError(403, "Admin permission required")
            rows = db.execute(
                "SELECT generation_mode,latency_ms,citation_count,rating,reason "
                "FROM query_events WHERE tenant=? AND created>=? "
                "ORDER BY created DESC,id DESC LIMIT 10000",
                (p.tenant, time() - days * 86400),
            ).fetchall()
        total = len(rows)
        rated = sum(r["rating"] is not None for r in rows)
        helpful = sum(r["rating"] == "helpful" for r in rows)
        durations = sorted(r["latency_ms"] for r in rows)
        modes: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for row in rows:
            modes[row["generation_mode"]] = modes.get(row["generation_mode"], 0) + 1
            if row["rating"] == "not_helpful" and row["reason"]:
                reasons[row["reason"]] = reasons.get(row["reason"], 0) + 1
        return {
            "window_days": days,
            "retention_days": 30,
            "max_retained_queries": 10000,
            "queries": total,
            "rated_queries": rated,
            "helpful": helpful,
            "not_helpful": rated - helpful,
            "feedback_coverage": rated / total if total else None,
            "helpful_rate_among_rated": helpful / rated if rated else None,
            "without_sources": sum(r["citation_count"] == 0 for r in rows),
            "generation_modes": modes,
            "negative_reasons": reasons,
            "latency_ms": {
                "p50": durations[ceil(total * 0.5) - 1] if total else None,
                "p95": durations[ceil(total * 0.95) - 1] if total else None,
            },
            "sample_at_capacity": total == 10000,
        }

    def prune_measurements(self):
        """Operator maintenance for inactive tenants; preserves document history."""
        with self.connection(write=True) as db:
            before = db.execute("SELECT count(*) FROM query_events").fetchone()[0]
            tenants = db.execute("SELECT DISTINCT tenant FROM query_events").fetchall()
            now = time()
            for row in tenants:
                self._prune_measurements(db, row["tenant"], now)
            after = db.execute("SELECT count(*) FROM query_events").fetchone()[0]
        return before - after
