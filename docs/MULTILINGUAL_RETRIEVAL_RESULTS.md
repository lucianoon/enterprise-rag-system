# Embeddings multilíngues e cross-encoder: resultados medidos

Pergunta: um modelo denso multilíngue real, pequeno e rodando em CPU, supera a
busca lexical no `corporate_pt_v1`? Até aqui a resposta do repositório era não:
o melhor resultado de teste era o lexical legado (Recall@5 = 0,9571), e o
híbrido com reranker, padrão da API, ficava em 0,8429.

**Resposta curta: sim, neste conjunto.** No split de teste, o vetor
`multilingual-e5-small` sozinho alcança Recall@5 = 0,9714 e MRR@5 = 0,8905;
RRF (BM25 + e5) alcança MRR@5 = 0,9429 com a mesma recuperação. O cross-encoder
multilíngue empata com RRF + e5 em Recall e MRR, custando cerca de 30 a 50 vezes
mais latência. As ressalvas de dados sintéticos continuam valendo (abaixo).

## Modelos, revisões fixadas e ambiente

| Papel | Modelo | Revisão (commit do Hugging Face) | Licença |
|---|---|---|---|
| Embeddings (padrão) | `intfloat/multilingual-e5-small` (384 dims) | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | MIT |
| Embeddings (comparação) | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dims) | `e8f8c211226b894fcb81acc59f3b34ba3efd5f42` | Apache-2.0 |
| Cross-encoder | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | `1427fd652930e4ba29e8149678df786c240d8825` | Apache-2.0 |

- Python 3.12.13, Windows 11 (10.0.26200), Intel Core i7-1185G7, 16 GB, só CPU.
- sentence-transformers 6.1.0, torch 2.14.0+cpu, NumPy 2.5.1, Pydantic 2.13.5.
- Corpus SHA-256 `060423af4c6eff89c7cde4f9d6fefb8fd86665f21f6e14cf539dfe4df0c755d9`,
  queries SHA-256 `e513ec36756e386602e27342329abd2ede1871bc2d0afcc23cb183a1d91dd125`.
- Código-fonte SHA-256 `7406e45ca6fae5e5217771ee3bb778a94c3b3ed750d613c6bb1d049b479a21e8`.
- E5 recebe os prefixos `query: ` / `passage: `; vetores normalizados, cosseno exato em memória.
- Cross-encoder reordena os 20 primeiros candidatos da primeira etapa (título + texto do chunk).

Relatórios completos, com ranking por pergunta:
[e5, teste](results/multilingual-e5-small-test.json) e
[cross-encoder, teste](results/cross-encoder-mmarco-test.json).

## Teste (35 perguntas respondíveis)

| Estratégia | R@1 | R@3 | R@5 | MRR@5 | nDCG@5 | p95@5 ms |
|---|---:|---:|---:|---:|---:|---:|
| lexical legado, analisador antigo (referência anterior) | 0.5857 | 0.8571 | 0.9571 | 0.7743 | 0.8080 | — |
| hybrid-rerank + hashing (padrão da API) | 0.5714 | 0.8429 | 0.8857 | 0.7595 | 0.7807 | — |
| lexical | 0.6857 | 0.8571 | 0.9143 | 0.8238 | 0.8335 | 0.6 |
| bm25 | 0.7429 | 0.8857 | 0.9429 | 0.8667 | 0.8727 | 0.4 |
| vector (e5) | 0.7571 | 0.9714 | 0.9714 | 0.8905 | 0.9112 | 56.3 |
| hybrid (0,55 lex + 0,45 e5) | 0.7143 | 0.8571 | 0.9143 | 0.8429 | 0.8478 | 46.3 |
| hybrid-rerank (e5) | 0.7000 | 0.8857 | 0.9286 | 0.8643 | 0.8691 | 56.3 |
| **rrf (BM25 + e5)** | **0.8429** | 0.9571 | **0.9714** | **0.9429** | 0.9445 | 49.4 |
| bm25-ce | 0.8429 | 0.9714 | 0.9714 | 0.9429 | 0.9503 | 1599.2 |
| rrf-ce | 0.8429 | 0.9714 | 0.9714 | 0.9429 | 0.9503 | 2547.8 |
| vector (MiniLM-L12) | 0.6429 | 0.8571 | 0.9000 | 0.7867 | 0.8097 | 35.9 |
| hybrid (MiniLM-L12) | 0.7571 | 0.9143 | 0.9571 | 0.8833 | 0.8909 | 135.3 |
| rrf (BM25 + MiniLM-L12) | 0.7429 | 0.9429 | 0.9571 | 0.8762 | 0.8871 | 40.0 |

As duas primeiras linhas vêm das referências de hashing (antes e depois da
unificação do analisador) e não medem latência comparável. Estratégias com
cross-encoder foram executadas com `--repeats 1`; as demais com 5 repetições.
As latências são de um notebook sem carga controlada, com outros processos
ativos, e servem só como ordem de grandeza.

## Desenvolvimento (35 perguntas respondíveis)

| Estratégia | R@1 | R@3 | R@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| lexical | 0.7286 | 0.8429 | 0.9143 | 0.8414 | 0.8551 |
| bm25 | 0.7000 | 0.9143 | 0.9429 | 0.8405 | 0.8664 |
| vector (e5) | 0.9286 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| hybrid (e5) | 0.7286 | 0.8714 | 0.9143 | 0.8486 | 0.8609 |
| hybrid-rerank (e5) | 0.7571 | 0.8571 | 0.8571 | 0.8190 | 0.8286 |
| rrf (BM25 + e5) | 0.7857 | 0.9714 | 1.0000 | 0.9167 | 0.9378 |
| bm25-ce | 0.9000 | 1.0000 | 1.0000 | 0.9810 | 0.9834 |
| rrf-ce | 0.9000 | 0.9714 | 1.0000 | 0.9786 | 0.9814 |

## Leitura honesta

- **O modelo denso é o componente que mais contribui.** e5 sozinho supera todas
  as configurações lexicais em Recall@3/5, MRR e nDCG no teste. No dev chega a
  MRR@5 = 1,0, o que sugere que as perguntas do dev são mais próximas do texto
  dos documentos que as do teste (o teste tem mais paráfrases).
- **A fusão por score (`hybrid`, 0,55/0,45) desperdiça o ganho**: escalas
  diferentes fazem o score lexical dominar. RRF, que funde posições, é a fusão
  que preserva o ganho e é a candidata natural a padrão com embeddings reais.
- **O cross-encoder não se paga aqui.** No teste, empata com RRF + e5 em Recall
  e MRR e melhora nDCG@5 em 0,006, com latência de 1,6 a 2,5 s por consulta em
  CPU. No dev ele supera RRF + e5 (MRR@5 0,9167 → 0,9810), mas não o vetor e5
  sozinho (1,0). Pode valer em corpora maiores ou com GPU; não há evidência
  disso neste conjunto.
- **MiniLM-L12 é mais fraco que e5** como vetor isolado (Recall@5 0,9000), mas
  combinado ainda empata com o lexical legado em Recall@5.
- Nenhuma configuração resolve perguntas sem resposta: todas devolvem
  candidatos (`unanswerable_return_rate = 1,0`). Isso exige um limiar calibrado
  ou verificação da resposta, não um retriever melhor.

## Limitações

- 30 documentos fictícios e 70 perguntas respondíveis, com autoria assistida por
  IA e sem anotação independente. O teste é conhecido e já foi usado como
  regressão: **não é uma avaliação cega**. Os ganhos precisam ser confirmados
  num conjunto novo antes de mudar o padrão da API.
- Nenhum peso, limiar ou modelo foi ajustado neste conjunto; os modelos foram
  escolhidos antes da medição (multilíngues, pequenos, licença permissiva).
- A CI não roda esta matriz (download de ~0,5 GB e torch). As referências de
  CI continuam sendo hashing e TF-IDF; os relatórios acima são versionados como
  evidência, e a comparação recusa relatórios com modelo ou revisão diferentes.
- O download depende de acesso a `huggingface.co`; atrás de proxy TLS
  corporativo, configure `REQUESTS_CA_BUNDLE`/`SSL_CERT_FILE` com a cadeia local.

## Reproduzir

```bash
uv sync --extra dev --extra extras --extra semantic --locked
uv run python -m enterprise_rag_system.benchmark --split test \
  --backend sentence-transformer \
  --strategies lexical vector hybrid hybrid-rerank bm25 rrf \
  --output docs/results/multilingual-e5-small-test.json
uv run python -m enterprise_rag_system.benchmark --split test \
  --backend sentence-transformer --strategies bm25-ce rrf-ce --repeats 1 \
  --output docs/results/cross-encoder-mmarco-test.json
uv run python -m enterprise_rag_system.benchmark --split test \
  --backend sentence-transformer \
  --st-model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 \
  --st-revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 \
  --strategies vector hybrid rrf --output benchmark-minilm-test.json
```

Para usar o modelo na API de demonstração: `RAG_EMBEDDING_BACKEND=sentence-transformer`
(`RAG_ST_MODEL` / `RAG_ST_REVISION` trocam o modelo) e `RAG_RETRIEVAL_MODE=rrf`.
Em Python, `RAGPipeline(chunks, reranker=CrossEncoderReranker(), rerank_pool=20)`
ativa o cross-encoder no lugar do reranker heurístico.
