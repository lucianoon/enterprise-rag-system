"""Small synthetic retrieval baseline; not a market benchmark. Uses real embeddings/Qdrant."""

import json
import os
import tempfile
import uuid
from pathlib import Path
from time import perf_counter

from enterprise_rag_system.product_reranker import rerank
from enterprise_rag_system.product_store import Registry
from enterprise_rag_system.product_vectors import ProductVectors
from enterprise_rag_system.ranking import BM25Index

DOCS = [
    (
        "travel",
        "Reembolso",
        "Despesas de viagens profissionais são restituídas após envio dos "
        "comprovantes pelo portal financeiro em até trinta dias.",
    ),
    (
        "access",
        "Credenciais",
        "Para recuperar o acesso, solicite redefinição da senha à equipe de suporte "
        "pelo portal de identidade.",
    ),
    (
        "leave",
        "Férias",
        "O descanso anual deve ser solicitado ao gestor com antecedência mínima de "
        "quarenta e cinco dias.",
    ),
    (
        "storage",
        "Amazon S3",
        "Amazon S3 é um serviço de armazenamento de objetos organizado em buckets. "
        "Versionamento permite recuperar versões anteriores dos objetos.",
    ),
    (
        "backup",
        "Continuidade",
        "Backups são executados diariamente e mantidos por noventa dias. A "
        "restauração deve ser testada mensalmente.",
    ),
    (
        "pastor",
        "Luiz Hermínio",
        "Luiz Hermínio é pastor evangélico ligado ao MEVAM. Seu ministério promove "
        "estudos bíblicos e formação cristã.",
    ),
]
CASES = [
    ("Como pedir reembolso de viagem?", "travel"),
    ("Como recuperar o dinheiro que gastei numa visita profissional?", "travel"),
    ("Esqueci minha senha. O que fazer?", "access"),
    ("Não consigo entrar na minha conta.", "access"),
    ("Quanto tempo antes devo solicitar férias?", "leave"),
    ("How far ahead must I request annual leave?", "leave"),
    ("Onde guardar objetos em buckets?", "storage"),
    ("How can I recover an earlier object version?", "storage"),
    ("Por quanto tempo guardamos backups?", "backup"),
    ("Como verificar se a recuperação de dados funciona?", "backup"),
    ("Luiz Hermínio é pastor?", "pastor"),
    ("Quem é o líder evangélico associado ao MEVAM?", "pastor"),
]


def main():
    os.environ["RAG_PRODUCT_VECTOR_STORE"] = "qdrant"
    with tempfile.TemporaryDirectory() as folder:
        index = ProductVectors(Registry(Path(folder) / "eval.sqlite3"))
        index.remote.collection = "evaluation_" + uuid.uuid4().hex
        rows = [{"doc_id": key, "title": title, "text": text} for key, title, text in DOCS]
        chunks = index.chunks(rows)
        lexical = BM25Index({c.chunk_id: f"{c.title} {c.text}" for c in chunks})
        try:
            index.index("evaluation", chunks)
            results = []
            for question, expected in CASES:
                scores = lexical.score(question)
                baseline = sorted(
                    (c for c in chunks if scores.get(c.chunk_id, 0) > 0),
                    key=lambda c: (-scores[c.chunk_id], c.chunk_id),
                )[:3]
                started = perf_counter()
                ranked = index.rank("evaluation", chunks, question, scores, 12)
                reranked, rerank_mode = rerank(question, ranked, 3)
                results.append(
                    {
                        "question": question,
                        "expected": expected,
                        "bm25": [c.doc_id for c in baseline],
                        "hybrid": [c.doc_id for c in ranked[:3]],
                        "reranked": [c.doc_id for c in reranked],
                        "rerank_mode": rerank_mode,
                        "latency_ms": round((perf_counter() - started) * 1000, 2),
                    }
                )
            report = {
                "scope": "12 synthetic questions, 6 short documents; not a production benchmark",
                "model": index.model,
                "backend": "qdrant",
                "cases": results,
            }
            for mode in ["bm25", "hybrid", "reranked"]:
                report[mode] = {
                    "recall_at_1": sum(
                        bool(r[mode]) and r[mode][0] == r["expected"] for r in results
                    )
                    / len(results),
                    "recall_at_3": sum(r["expected"] in r[mode] for r in results) / len(results),
                    "mrr_at_3": sum(
                        1 / (r[mode].index(r["expected"]) + 1) if r["expected"] in r[mode] else 0
                        for r in results
                    )
                    / len(results),
                }
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            if index.remote.client.collection_exists(index.remote.collection):
                index.remote.client.delete_collection(index.remote.collection)
            index.remote.client.close()


if __name__ == "__main__":
    main()
