"""Disk-backed streaming uploads and background indexing with explicit retry after restart."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from enterprise_rag_system.product_store import DocumentInput, StoreError


class LargeImports:
    def __init__(self, registry, vectors):
        self.registry = registry
        self.vectors = vectors
        self.directory = registry.path.parent / "uploads"
        self.directory.mkdir(exist_ok=True)
        self.directory.chmod(0o700)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-import")
        self.slots = BoundedSemaphore(4)
        with registry.connection(write=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS import_jobs (
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, owner TEXT NOT NULL,
                filename TEXT NOT NULL, path TEXT NOT NULL, state TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '', characters INTEGER NOT NULL DEFAULT 0,
                chunks INTEGER NOT NULL DEFAULT 0)""")
            db.execute(
                "UPDATE import_jobs SET state='interrupted', detail='Processamento "
                "interrompido; retome a indexação.' "
                "WHERE state IN ('queued','extracting','indexing')"
            )

    def update(self, job_id, state, detail="", characters=0, chunks=0):
        with self.registry.connection(write=True) as db:
            db.execute(
                "UPDATE import_jobs SET state=?,detail=?,characters=?,chunks=? WHERE id=?",
                (state, detail, characters, chunks, job_id),
            )

    def submit(self, job_id, path, filename, token, principal):
        if not self.slots.acquire(blocking=False):
            raise StoreError(429, "A fila está cheia. Tente novamente após uma indexação concluir.")
        try:
            with self.registry.connection(write=True) as db:
                db.execute(
                    "INSERT INTO import_jobs(id,tenant,owner,filename,path,state) "
                    "VALUES(?,?,?,?,?,?)",
                    (job_id, principal.tenant, principal.user, filename, str(path), "queued"),
                )
            self.pool.submit(self.process, job_id, token)
        except Exception:
            self.slots.release()
            raise

    def list_jobs(self, token):
        with self.registry.connection() as db:
            principal = self.registry._principal(db, token)
            rows = db.execute(
                "SELECT id FROM import_jobs WHERE tenant=? AND owner=? "
                "AND state != 'ready' ORDER BY rowid DESC LIMIT 10",
                (principal.tenant, principal.user),
            ).fetchall()
        return [row["id"] for row in rows]

    def read(self, job_id, token):
        with self.registry.connection() as db:
            principal = self.registry._principal(db, token)
            row = db.execute(
                "SELECT * FROM import_jobs WHERE id=? AND tenant=? AND owner=?",
                (job_id, principal.tenant, principal.user),
            ).fetchone()
        if row is None:
            raise StoreError(404, "Importação não encontrada")
        return {
            key: row[key] for key in ("id", "filename", "state", "detail", "characters", "chunks")
        }

    def retry(self, job_id, token):
        job = self.read(job_id, token)
        if job["state"] not in {"failed", "interrupted"}:
            raise StoreError(409, "A importação não pode ser retomada neste estado")
        if not self.slots.acquire(blocking=False):
            raise StoreError(429, "A fila está cheia")
        with self.registry.connection(write=True) as db:
            changed = db.execute(
                "UPDATE import_jobs SET state='queued',detail='' WHERE id=? AND state "
                "IN ('failed','interrupted')",
                (job_id,),
            ).rowcount
        if not changed:
            self.slots.release()
            raise StoreError(409, "Importação já retomada")
        self.pool.submit(self.process, job_id, token)

    def process(self, job_id, token):
        output = self.directory / (job_id + ".extracted.json")
        try:
            with self.registry.connection() as db:
                principal = self.registry._principal(db, token)
                if principal.role not in {"admin", "editor"}:
                    raise StoreError(403, "Acesso de edição necessário")
                row = db.execute("SELECT * FROM import_jobs WHERE id=?", (job_id,)).fetchone()
            self.update(job_id, "extracting")
            # Never pass provider credentials into parsers. Limits on individual OCR
            # commands remain; no aggregate page, character or job-duration ceiling.
            import os

            env = {k: v for k, v in os.environ.items() if k in {"PATH", "PYTHONPATH", "LANG"}}
            env.update(
                RAG_LARGE_IMPORT="true",
                OMP_THREAD_LIMIT="1",
                LC_ALL="C",
                RAG_IMPORT_MEMORY_MB=os.getenv("RAG_IMPORT_MEMORY_MB", "768"),
            )
            with output.open("wb") as stream:
                output.chmod(0o600)
                result = subprocess.run(
                    [sys.executable, "-m", "enterprise_rag_system.file_import", row["path"]],
                    stdout=stream,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    check=False,
                )
            if result.returncode:
                raise ValueError(
                    "Extração excedeu os recursos disponíveis ou o arquivo é inválido."
                )
            payload = json.loads(output.read_text())
            if "error" in payload:
                raise ValueError(payload["error"])
            text = payload["text"]
            title = Path(row["filename"]).stem[:300] or "Documento"
            chunks = self.vectors.chunks([{"doc_id": job_id, "title": title, "text": text}])
            self.update(job_id, "indexing", characters=len(text), chunks=len(chunks))
            self.vectors.index(principal.tenant, chunks)
            # A retry after a crash between commit and ready must not duplicate the document.
            _, _, rows = self.registry.documents(token)
            existing = next((r for r in rows if r["doc_id"] == job_id), None)
            if existing is None:
                self.registry.write_document(
                    token,
                    job_id,
                    DocumentInput(
                        title=title, text=text, visibility="private", expected_revision=0
                    ),
                )
            self.update(job_id, "ready", "Documento pronto para perguntas.", len(text), len(chunks))
        except (ValueError, StoreError) as exc:
            self.update(job_id, "failed", str(exc))
        except Exception:
            self.update(
                job_id,
                "failed",
                "Não foi possível concluir. Verifique o arquivo, o espaço em disco e os "
                "serviços; depois retome.",
            )
        finally:
            output.unlink(missing_ok=True)
            self.slots.release()
