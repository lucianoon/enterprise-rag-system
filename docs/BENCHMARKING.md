# Protocolo de benchmark

Este documento define como medir mudanças de recuperação sem transformar uma
melhora subjetiva em afirmação de desempenho.

## Objetivo

Comparar configurações do pipeline usando o mesmo corpus, o mesmo conjunto de
consultas rotuladas e o mesmo ambiente. As métricas principais são:

- **Recall@K**: cobertura dos documentos relevantes nas primeiras K posições;
- **MRR**: posição do primeiro documento relevante;
- **latência**: custo operacional observado por consulta.

Métricas de recuperação não medem, sozinhas, qualidade factual da resposta.
Quando a mudança afeta geração, reporte também a fidelidade do endpoint
`/evaluate/answer`.

## Benchmark padrão

O corpus versionado está em `data/sample/policies.jsonl` e as consultas
rotuladas em `data/eval/retrieval_v1.jsonl`.

```bash
uv sync --extra dev --extra extras

# Baseline determinística e offline
RAG_EMBEDDING_BACKEND=hashing \
RAG_VECTOR_STORE=memory \
uv run python -m enterprise_rag_system.evaluation --top-k 1

RAG_EMBEDDING_BACKEND=hashing \
RAG_VECTOR_STORE=memory \
uv run python -m enterprise_rag_system.evaluation --top-k 3
```

Para testar TF-IDF, troque `RAG_EMBEDDING_BACKEND` por `tfidf`. Para Qdrant,
suba o serviço com `docker compose up -d qdrant` e use
`RAG_VECTOR_STORE=qdrant`.

## Regras de comparação

1. Use o mesmo commit de dados para baseline e candidato.
2. Rode cada configuração pelo menos cinco vezes ao comparar latência.
3. Informe mediana e p95; não use apenas a melhor execução.
4. Registre hardware, sistema operacional, versão do Python e backend.
5. Não compare hashing/TF-IDF com embeddings densos sem explicitar a diferença.
6. Não ajuste pesos usando as mesmas consultas reservadas para a avaliação final.

## Relatório para pull requests

Inclua uma tabela como esta:

| Configuração | Recall@1 | Recall@3 | MRR | Latência mediana | p95 |
|---|---:|---:|---:|---:|---:|
| baseline | — | — | — | — | — |
| candidato | — | — | — | — | — |
| diferença | — | — | — | — | — |

Registre também:

- commit e comando utilizados;
- corpus e dataset;
- pesos lexical/vetorial;
- tamanho do pool de candidatos;
- backend de embeddings e vector store;
- regressões conhecidas e justificativa do trade-off.

Os símbolos “—” são placeholders. Não publique números sem executar o
benchmark no ambiente descrito.
