"""Dedicated pilot API: persistent documents, scoped credentials and evidence-first answers."""

import base64
import binascii
import json
import logging
import os
import re
import secrets
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import BoundedSemaphore
from time import perf_counter
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as APIPath
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from enterprise_rag_system import llm_client
from enterprise_rag_system.answer_verification import review
from enterprise_rag_system.evidence_context import expand_context
from enterprise_rag_system.file_import import extract
from enterprise_rag_system.ingestion import chunk_documents
from enterprise_rag_system.large_import import LargeImports
from enterprise_rag_system.models import Chunk, Document
from enterprise_rag_system.product_profiles import load_profile
from enterprise_rag_system.product_reranker import rerank
from enterprise_rag_system.product_retrieval import LexicalIndexCache, lexical_question
from enterprise_rag_system.product_store import DocumentInput, Principal, Registry, StoreError
from enterprise_rag_system.product_vectors import ProductVectors

logger = logging.getLogger(__name__)


class FileImport(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(max_length=7 * 1024 * 1024)


class IndexedImport(FileImport):
    doc_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class ProductQuery(BaseModel):
    answer_style: Literal["concise", "detailed"] = "concise"
    model_config = ConfigDict(extra="forbid")
    doc_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=5)

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Question must not be blank")
        return value


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["helpful", "not_helpful"]
    reason: (
        Literal["missing_information", "irrelevant_sources", "incorrect_answer", "other"] | None
    ) = None

    @model_validator(mode="after")
    def consistent(self):
        if self.rating == "helpful" and self.reason is not None:
            raise ValueError("Helpful feedback must not include a negative reason")
        return self


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    expected_revision: int = Field(ge=1)


class BodyLimit:
    """Bound actual received bytes before JSON parsing, including chunked requests."""

    def __init__(self, app, limit: int = 131072):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                    ],
                }
            await send(message)

        if scope["path"] == "/uploads" and scope["method"] == "POST":
            return await self.app(scope, receive, secure_send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            limit = (
                7 * 1024 * 1024
                if scope["path"] in {"/imports/extract", "/imports/index"}
                else self.limit
            )
            if len(body) > limit:
                response = JSONResponse({"detail": "Request exceeds size limit"}, status_code=413)
                return await response(scope, receive, secure_send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, secure_send)


def credential(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Bearer credential required")
    return authorization[7:]


def valid_citations(text: str, count: int) -> bool:
    """Structural check only: markers cannot establish factual entailment."""
    markers = re.findall(r"\[(\d+)\]", text)
    return (
        bool(markers)
        and all(1 <= int(m) <= count for m in markers)
        and all(
            re.search(r"\[\d+\]", paragraph)
            for paragraph in text.split("\n\n")
            if paragraph.strip()
        )
    )


@dataclass
class ProductContext:
    """Everything the product routes share, created once per application."""

    registry: Registry
    generation: str
    profile: str
    system_prompt: str
    prompt_sha256: str
    vectors: ProductVectors | None
    uploads: LargeImports | None
    lexical: LexicalIndexCache = field(default_factory=LexicalIndexCache)
    slots: BoundedSemaphore = field(default_factory=lambda: BoundedSemaphore(2))
    import_slots: BoundedSemaphore = field(default_factory=lambda: BoundedSemaphore(2))

    def authorize(
        self, token: str, roles: set[str] | None = None, message: str = ""
    ) -> Principal:
        """Resolve the credential and, when ``roles`` is given, require one of them."""
        with self.registry.connection() as db:
            principal = self.registry._principal(db, token)
        if roles is not None and principal.role not in roles:
            raise StoreError(403, message)
        return principal

    def generation_prompt(self, answer_style: str) -> str:
        style = (
            "Responda em um parágrafo curto, idealmente até 100 palavras."
            if answer_style == "concise"
            else "Desenvolva a explicação em parágrafos organizados, sem repetições."
        )
        return self.system_prompt + "\n\n" + style


def create_product_app(
    database: Path, *, generation: str = "extractive", profile: str = "default"
) -> FastAPI:
    if generation not in ("extractive", "llm"):
        raise ValueError("RAG_PRODUCT_GENERATION must be extractive or llm")
    system_prompt, prompt_sha256 = load_profile(profile)
    registry = Registry(database)
    app = FastAPI(title="Enterprise RAG — piloto", version="0.4.0")
    app.state.registry = registry
    vectors = ProductVectors(registry) if os.getenv("RAG_PRODUCT_RETRIEVAL") == "hybrid" else None
    app.state.vectors = vectors
    ctx = ProductContext(
        registry=registry,
        generation=generation,
        profile=profile,
        system_prompt=system_prompt,
        prompt_sha256=prompt_sha256,
        vectors=vectors,
        uploads=LargeImports(registry, vectors) if vectors is not None else None,
    )
    app.state.lexical_cache = ctx.lexical
    app.add_middleware(BodyLimit)
    _register_error_handlers(app)
    _register_system_routes(app, ctx)
    _register_import_routes(app, ctx)
    _register_document_routes(app, ctx)
    _register_query_routes(app, ctx)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StoreError)
    async def store_error(request, exc: StoreError):
        headers = {"Retry-After": "60"} if exc.status == 429 else None
        return JSONResponse({"detail": exc.message}, status_code=exc.status, headers=headers)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request, exc):
        logger.warning("Registry unavailable (%s)", type(exc).__name__)
        return JSONResponse({"detail": "Registry temporarily unavailable"}, status_code=503)


def _render_home() -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    html = (Path(__file__).parent / "product.html").read_text(encoding="utf-8")
    html = html.replace("<script>", f'<script nonce="{nonce}">')
    html = html.replace("<style>", f'<style nonce="{nonce}">')
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": "default-src 'none'; connect-src 'self'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'; "
            f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'"
        },
    )


def _register_system_routes(app: FastAPI, ctx: ProductContext) -> None:
    registry, vectors = ctx.registry, ctx.vectors

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        with registry.connection() as db:
            db.execute("SELECT 1 FROM users LIMIT 1").fetchone()
        if vectors is not None and vectors.remote is not None:
            try:
                vectors.remote.prepare()
            except Exception as exc:
                raise HTTPException(503, "Qdrant unavailable") from exc
        return {"status": "ready"}

    @app.get("/", response_class=HTMLResponse)
    def home():
        return _render_home()

    @app.get("/profile")
    def profile_info():
        return {
            "profile": ctx.profile,
            "generation": ctx.generation,
            "retrieval": "hybrid" if vectors else "bm25",
            "vector_store": vectors.storage if vectors else None,
            "prompt_sha256": ctx.prompt_sha256,
            "identity": (
                "Assistente de IA para estudos cristãos, inspirado em temas públicos do "
                "Pr. Luiz Hermínio. Não é o pastor nem representa oficialmente o MEVAM."
                if ctx.profile == "luiz-herminio"
                else "Assistente de consulta documental"
            ),
        }

    @app.get("/me")
    def me(token: str = Depends(credential)):
        principal = ctx.authorize(token)
        return {"tenant": principal.tenant, "user": principal.user, "role": principal.role}

    @app.post("/index/sync")
    def sync_index(token: str = Depends(credential)):
        ctx.authorize(token, {"admin"}, "Admin permission required")
        if vectors is None:
            raise HTTPException(409, "Hybrid retrieval is disabled")
        if not ctx.slots.acquire(blocking=False):
            raise HTTPException(429, "Indexing busy")
        try:
            return vectors.sync(token)
        except Exception as exc:
            raise HTTPException(503, "Semantic indexing unavailable; retry later") from exc
        finally:
            ctx.slots.release()


def _extract_file(ctx: ProductContext, document: FileImport, token: str) -> dict:
    """Authorize an editor, then run the isolated extractor under a bounded slot."""
    ctx.authorize(token, {"admin", "editor"}, "Editor permission required")
    if not ctx.import_slots.acquire(blocking=False):
        raise HTTPException(429, "Extração ocupada. Tente novamente em instantes.")
    try:
        try:
            data = base64.b64decode(document.content, validate=True)
            result = extract(data, document.filename)
        except (ValueError, binascii.Error) as exc:
            raise HTTPException(422, str(exc)) from exc
        # Re-check the credential: it may have been revoked during extraction.
        ctx.authorize(token)
        return result
    finally:
        ctx.import_slots.release()


def _register_import_routes(app: FastAPI, ctx: ProductContext) -> None:
    registry, vectors, uploads = ctx.registry, ctx.vectors, ctx.uploads

    @app.post("/imports/extract")
    def import_file(document: FileImport, token: str = Depends(credential)):
        return _extract_file(ctx, document, token)

    @app.post("/uploads", status_code=202)
    async def upload_document(
        request: Request,
        filename: str = Query(min_length=1, max_length=255),
        token: str = Depends(credential),
    ):
        principal = ctx.authorize(token, {"admin", "editor"}, "Acesso de edição necessário")
        if uploads is None:
            raise HTTPException(409, "Ative a busca híbrida")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".txt", ".md", ".pdf", ".docx"}:
            raise HTTPException(422, "Use TXT, MD, PDF ou DOCX")
        job_id = str(uuid.uuid4())
        path = uploads.directory / (job_id + suffix)
        try:
            size = 0
            with path.open("xb") as stream:
                path.chmod(0o600)
                async for chunk in request.stream():
                    if shutil.disk_usage(uploads.directory).free < len(chunk) + 64 * 1024**2:
                        raise HTTPException(507, "Espaço em disco insuficiente")
                    stream.write(chunk)
                    size += len(chunk)
            if not size:
                raise HTTPException(422, "Arquivo vazio")
            uploads.submit(job_id, path, filename, token, principal)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {"job_id": job_id, "state": "queued"}

    @app.get("/uploads")
    def list_uploads(token: str = Depends(credential)):
        ctx.authorize(token)
        return {"jobs": uploads.list_jobs(token) if uploads else []}

    @app.get("/uploads/{job_id}")
    def upload_status(job_id: str, token: str = Depends(credential)):
        if uploads is None:
            raise HTTPException(409, "Ative a busca híbrida")
        return uploads.read(job_id, token)

    @app.post("/uploads/{job_id}/retry")
    def retry_upload(job_id: str, token: str = Depends(credential)):
        if uploads is None:
            raise HTTPException(409, "Ative a busca híbrida")
        uploads.retry(job_id, token)
        return {"job_id": job_id, "state": "queued"}

    @app.post("/imports/index")
    def index_file(document: IndexedImport, token: str = Depends(credential)):
        # Extract first. Do not create an empty document or overwrite an existing one.
        extracted = _extract_file(ctx, document, token)
        title = Path(document.filename).stem.strip() or "Documento"
        principal = ctx.authorize(token)
        chunks = chunk_documents(
            [Document(doc_id=document.doc_id, title=title, text=extracted["text"])]
        )
        if vectors is None:
            raise HTTPException(409, "Ative a busca híbrida antes de indexar arquivos.")
        if not ctx.slots.acquire(blocking=False):
            raise HTTPException(429, "Indexação ocupada. Tente novamente.")
        try:
            try:
                vectors.index(principal.tenant, chunks)
            except Exception as exc:
                raise HTTPException(
                    503, "Falha ao gerar embeddings. Tente indexar novamente."
                ) from exc
            saved = registry.write_document(
                token,
                document.doc_id,
                DocumentInput(
                    title=title, text=extracted["text"], visibility="private", expected_revision=0
                ),
            )
            return {
                **saved,
                "doc_id": document.doc_id,
                "title": title,
                "characters": len(extracted["text"]),
                "chunks": len(chunks),
                "ocr_pages": extracted["ocr_pages"],
                "indexing": "ready",
            }
        finally:
            ctx.slots.release()


def _register_document_routes(app: FastAPI, ctx: ProductContext) -> None:
    registry, vectors = ctx.registry, ctx.vectors

    @app.get("/documents")
    def documents(include_deleted: bool = False, token: str = Depends(credential)):
        _, revision, rows = registry.documents(token, include_deleted=include_deleted)
        return {
            "corpus_revision": revision,
            "documents": [
                {
                    "doc_id": r["doc_id"],
                    "title": r["title"],
                    "revision": r["revision"],
                    "deleted": bool(r["deleted"]),
                }
                for r in rows
            ],
        }

    @app.get("/documents/{doc_id}")
    def document(doc_id: str, include_deleted: bool = False, token: str = Depends(credential)):
        _, _, rows = registry.documents(token, include_deleted=include_deleted)
        row = next((r for r in rows if r["doc_id"] == doc_id), None)
        if row is None:
            raise StoreError(404, "Document not found")
        return {
            **{key: row[key] for key in ("doc_id", "title", "text", "revision", "visibility")},
            "readers": json.loads(row["readers"]),
            "deleted": bool(row["deleted"]),
        }

    @app.get("/documents/{doc_id}/evidence")
    def evidence(
        doc_id: str,
        revision: int = Query(ge=1),
        chunk_index: int = Query(ge=0),
        token: str = Depends(credential),
    ):
        _, _, rows = registry.documents(token)
        row = next((r for r in rows if r["doc_id"] == doc_id), None)
        if row is None:
            raise StoreError(404, "Document not found")
        if row["revision"] != revision:
            raise StoreError(409, "O documento mudou. Consulte novamente para obter fontes atuais.")
        parts = chunk_documents([Document(doc_id=doc_id, title=row["title"], text=row["text"])])
        if chunk_index >= len(parts):
            raise StoreError(404, "Trecho não encontrado")
        start, stop = max(0, chunk_index - 1), min(len(parts), chunk_index + 2)
        return {
            "doc_id": doc_id,
            "title": row["title"],
            "revision": revision,
            "total_chunks": len(parts),
            "location_kind": "extracted_text",
            "chunks": [
                {"chunk_id": part.chunk_id, "text": part.text, "selected": index == chunk_index}
                for index, part in enumerate(parts[start:stop], start)
            ],
        }

    @app.put("/documents/{doc_id}")
    def save_document(
        document: DocumentInput,
        doc_id: str = APIPath(pattern=r"^[A-Za-z0-9_-]{1,80}$"),
        token: str = Depends(credential),
    ):
        result = registry.write_document(token, doc_id, document)
        if vectors:
            try:
                vectors.sync(token)
                result["indexing"] = "ready"
            except Exception:
                logger.warning("Document saved; semantic indexing pending")
                result["indexing"] = "pending"
        return result

    @app.delete("/documents/{doc_id}")
    def delete_document(
        doc_id: str,
        expected_revision: int = Query(ge=1),
        token: str = Depends(credential),
    ):
        return registry.delete_document(token, doc_id, expected_revision)

    @app.get("/documents/{doc_id}/history")
    def history(doc_id: str, token: str = Depends(credential)):
        return {"versions": registry.history(token, doc_id)}

    @app.post("/documents/{doc_id}/restore")
    def restore(doc_id: str, request: RestoreRequest, token: str = Depends(credential)):
        return registry.restore(token, doc_id, request.revision, request.expected_revision)

    @app.get("/audit")
    def audit(token: str = Depends(credential)):
        return {"events": registry.audit(token)}

    @app.put("/queries/{query_id}/feedback")
    def feedback(
        request: FeedbackRequest,
        query_id: str = APIPath(pattern=r"^[0-9a-f]{32}$"),
        token: str = Depends(credential),
    ):
        return registry.feedback(token, query_id, request.rating, request.reason)

    @app.get("/quality")
    def quality(days: int = Query(default=30, ge=1, le=30), token: str = Depends(credential)):
        return registry.quality(token, days)


@dataclass
class Retrieval:
    chunks: list[Chunk]
    selected: list[Chunk]
    retrieval_mode: str = "bm25"
    rerank_mode: str = "disabled"


def retrieve(ctx: ProductContext, tenant: str, rows: list, request: ProductQuery) -> Retrieval:
    """BM25 over the authorized snapshot; RRF with semantic vectors when enabled.

    ACL filtering already happened: ``rows`` holds only readable documents.
    """
    snapshot = ctx.lexical.get(tenant, rows)
    vectors = ctx.vectors
    question = lexical_question(request.question) if vectors else request.question
    scores, selected = snapshot.rank(question, request.top_k)
    result = Retrieval(chunks=list(snapshot.chunks), selected=selected)
    if vectors:
        try:
            use_rerank = os.getenv("RAG_PRODUCT_RERANK") == "true"
            candidates = vectors.rank(
                tenant,
                result.chunks,
                request.question,
                scores,
                30 if use_rerank else request.top_k,
            )
            if use_rerank:
                result.selected, result.rerank_mode = rerank(
                    request.question, candidates, request.top_k
                )
            else:
                result.selected = candidates
            result.retrieval_mode = "hybrid"
        except Exception:
            logger.warning("Semantic retrieval unavailable; using BM25")
            result.retrieval_mode = "bm25-semantic-fallback"
    return result


def build_citations(
    selected: list[Chunk], versions: dict[str, int], context_members: dict[str, list[str]]
) -> list[dict]:
    return [
        {
            "number": i,
            "doc_id": c.doc_id,
            "title": c.title,
            "chunk_id": c.chunk_id,
            "revision": versions[c.doc_id],
            "excerpt": c.text,
            "context_chunk_ids": context_members[c.chunk_id],
            "location_kind": "extracted_text",
        }
        for i, c in enumerate(selected, 1)
    ]


def generate_answer(
    ctx: ProductContext, request: ProductQuery, selected: list[Chunk], versions: dict[str, int]
) -> tuple[str, str]:
    """Extractive evidence by default; an LLM draft only with structurally valid citations."""
    if not selected:
        return (
            "Não encontrei trechos correspondentes nos documentos aos quais você tem acesso.",
            "abstained",
        )
    answer = "Trechos relacionados à pergunta:\n\n" + "\n\n".join(
        f"{c.text} [{i}]" for i, c in enumerate(selected, 1)
    )
    if ctx.generation != "llm":
        return answer, "extractive"
    context = "\n\n".join(
        f"[{i}] Documento: {c.title} · versão {versions[c.doc_id]}\n{c.text}"
        for i, c in enumerate(selected, 1)
    )
    prompt = ctx.generation_prompt(request.answer_style)
    try:
        candidate = llm_client.complete(
            prompt,
            f"Pergunta: {request.question}\n\nFontes:\n{context}",
            max_tokens=700,
        )
        if not valid_citations(candidate, len(selected)):
            candidate = llm_client.complete(
                prompt,
                f"Pergunta: {request.question}\n\nFontes:\n{context}\n\n"
                "Mantenha o nível de detalhe solicitado e responda em português. "
                "Cada parágrafo deve terminar com uma fonte "
                f"de [1] a [{len(selected)}]. "
                "Não copie números da bibliografia do documento. "
                "Se as fontes forem insuficientes, diga isso "
                "com a referência ao trecho.",
                max_tokens=700,
            )
        if valid_citations(candidate, len(selected)):
            return candidate, "llm-structurally-checked"
        return answer, "extractive-invalid-citations"
    except Exception:
        logger.warning("Generation failed; using extractive evidence")
        return answer, "extractive-provider-fallback"


def verify_answer(
    ctx: ProductContext,
    request: ProductQuery,
    answer: str,
    citations: list[dict],
    selected_count: int,
    mode: str,
) -> tuple[str, str, str, list[dict]]:
    """Evidence review of an LLM answer; abstain unless the reviewer says ``supported``.

    Returns ``(answer, mode, verification, citations)``.
    """
    verification = "unavailable"
    if mode == "llm-structurally-checked":
        try:
            report = review(request.question, answer, citations)
            if report.verdict == "revise":
                revised = llm_client.complete(
                    ctx.generation_prompt(request.answer_style),
                    json.dumps(
                        {
                            "question": request.question,
                            "sources": citations,
                            "draft": answer,
                            "review_issues": report.issues,
                        },
                        ensure_ascii=False,
                    )
                    + "\nReescreva a resposta corrigindo os problemas, somente com "
                    "suporte nas fontes. Preserve citações e o nível de detalhe.",
                    max_tokens=700,
                )
                if valid_citations(revised, selected_count):
                    report = review(request.question, revised, citations)
                    if report.verdict == "supported":
                        answer = revised
                else:
                    raise ValueError("Invalid revised citations")
            verification = report.verdict
        except Exception:
            logger.warning("Evidence review unavailable or invalid")
    if verification == "supported":
        return answer, "llm-evidence-reviewed", verification, citations
    answer = (
        "Não encontrei evidência suficiente nos trechos recuperados para "
        "responder com segurança. Tente uma pergunta mais específica."
        if verification in {"insufficient", "revise"}
        else "Não foi possível concluir a verificação da resposta. Tente novamente."
    )
    return answer, "abstained-" + verification, verification, []


def answer_query(ctx: ProductContext, request: ProductQuery, token: str) -> dict:
    started = perf_counter()
    registry = ctx.registry
    principal, revision, rows = registry.documents(token, consume_query=True)
    if request.doc_id is not None:
        rows = [row for row in rows if row["doc_id"] == request.doc_id]
        if not rows:
            raise StoreError(404, "Document not found")
    # ACL filtering precedes all lexical scoring, retrieval and generation.
    found = retrieve(ctx, principal.tenant, rows, request)
    selected = found.selected
    context_members = {c.chunk_id: [c.chunk_id] for c in selected}
    if ctx.generation == "llm":
        selected, context_members = expand_context(selected, found.chunks)
    versions = {r["doc_id"]: r["revision"] for r in rows}
    citations = build_citations(selected, versions, context_members)
    answer, mode = generate_answer(ctx, request, selected, versions)
    verification = "disabled"
    abstained = not selected
    if os.getenv("RAG_PRODUCT_VERIFY") == "true" and ctx.generation == "llm" and selected:
        answer, mode, verification, citations = verify_answer(
            ctx, request, answer, citations, len(selected), mode
        )
        abstained = verification != "supported"
    if mode in {"llm-structurally-checked", "llm-evidence-reviewed"}:
        used = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
        citations = [c for c in citations if c["number"] in used]
    latency_ms = round((perf_counter() - started) * 1000, 2)
    query_id = registry.record_query(token, revision, mode, latency_ms, len(citations))
    vectors = ctx.vectors
    return {
        "query_id": query_id,
        "answer": answer,
        "citations": citations,
        "abstained": abstained,
        "metadata": {
            "corpus_revision": revision,
            "generation_mode": mode,
            "verification": verification,
            "answer_style": request.answer_style,
            "retrieval_mode": found.retrieval_mode,
            "rerank_mode": found.rerank_mode,
            "embedding_model": vectors.model if vectors else None,
            "vector_store": vectors.storage if vectors else None,
            "editorial_profile": ctx.profile,
            "prompt_sha256": ctx.prompt_sha256,
            "latency_ms": latency_ms,
        },
    }


def _register_query_routes(app: FastAPI, ctx: ProductContext) -> None:
    @app.post("/query")
    def query(request: ProductQuery, token: str = Depends(credential)):
        if not ctx.slots.acquire(blocking=False):
            raise HTTPException(503, "Query capacity reached", headers={"Retry-After": "2"})
        try:
            return answer_query(ctx, request, token)
        finally:
            ctx.slots.release()
