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

## Benchmark corporativo em português

`corporate_pt_v1` contém 30 documentos fictícios e 80 consultas. Leia a
[ficha dos dados](../data/benchmarks/corporate_pt_v1/README.md): a autoria foi
assistida por IA, os rótulos não são independentes e o conjunto é um teste de
regressão, não uma avaliação externa de mercado.

```bash
# Desenvolvimento: inspecionar erros e formular hipóteses.
uv run python -m enterprise_rag_system.benchmark --split dev \
  --output benchmark-report.json

# A mesma matriz, com TF-IDF no componente vetorial (requer extra extras).
uv run python -m enterprise_rag_system.benchmark --split dev --backend tfidf \
  --output benchmark-report.json

# Teste congelado: falha se qualquer métrica de recuperação regredir.
uv run python -m enterprise_rag_system.benchmark --split test \
  --baseline data/benchmarks/corporate_pt_v1/baseline-hashing-test.json \
  --output benchmark-report.json
```

O comando constrói um índice em memória e compara:

| Estratégia | Componentes ativos |
|---|---|
| `lexical` | Score lexical existente: IDF e frequência logarítmica; não é BM25 completo |
| `vector` | Similaridade vetorial usando hashing ou TF-IDF |
| `hybrid` | Fusão atual: 0,55 lexical + 0,45 vetorial |
| `hybrid-rerank` | Fusão atual seguida pelo reranker heurístico da API |

`RAGPipeline.retrieve()` executa o mesmo caminho de evidências usado por
`query()`, com modos opcionais para ablação. A consulta da API mantém os
defaults anteriores. O benchmark injeta explicitamente embedder, armazenamento
em memória e gerador determinístico, mas não chama o gerador. Variáveis de
ambiente apontando para provedores, Qdrant ou modelos externos não acionam esses
serviços durante o benchmark.

Cada K é executado separadamente. O pool continua sendo `2 * K`, seguido pelo
corte em K; por isso a classificação em K=1 pode diferir da primeira posição de
uma execução em K=5 quando o reranking está ativo.

### Definição das métricas

As médias usam apenas consultas com documentos relevantes conhecidos:

- Recall@K: documentos relevantes distintos encontrados / total de relevantes.
- Precisão@K: documentos relevantes distintos encontrados / K.
- MRR@K: inverso da posição do primeiro documento relevante; zero se ausente.
- nDCG@K: ganho binário descontado por `log2(rank + 1)`, dividido pelo ranking ideal.

**K conta chunks retornados**, como na API. Repetições de um documento ocupam
posições, mas não recebem ganho adicional. O relatório mantém essas repetições
para diagnosticar desperdício de contexto. O ranking ideal usa até
`min(K, número de documentos relevantes)` fontes distintas. Essa convenção deve
ser considerada antes de comparar com ferramentas que deduplicam documentos
antes de aplicar K. As definições têm testes com resultados calculados à mão.

Perguntas sem resposta têm `metrics: null` e ficam fora das médias. A taxa
`unanswerable_return_rate` informa quantas receberam qualquer candidato, não
quantas tiveram resposta inventada. Nenhuma alegação sobre alucinação ou
fidelidade pode ser extraída desse número sem avaliar a geração separadamente.

### Latência e proveniência

O padrão realiza um aquecimento por consulta/configuração e cinco medições
subsequentes. O relatório agrega as medições de todas as consultas, inclusive
as sem resposta. A mediana e o p95 usam milissegundos; o p95 é o elemento
`ceil(0.95 * N)` na série ordenada. Não incluem LLM, rede, carga concorrente ou
construção do índice. O custo de construção aparece em `index_ms`; como o índice
é compartilhado entre ablações, esse campo não representa o custo de uma
implementação lexical isolada.

O JSON registra hashes SHA-256 do corpus e das queries, hash do código-fonte,
versões do Python e das bibliotecas de embeddings, arquitetura, dimensões,
split, contagens e resultados por consulta. Use `--repeats`, `--top-k`,
`--max-words`, `--corpus` e `--queries` para experimentos explícitos. As consultas
personalizadas precisam dos campos `query_id`, `question`, `relevant_doc_ids`,
`split` (`dev` ou `test`) e `category`. IDs duplicados, perguntas vazias ou
duplicadas entre splits e rótulos para documentos inexistentes são rejeitados.

### Gate de regressão

A CI compara hashing contra a referência congelada, com tolerância padrão zero
para as quatro métricas de cada estratégia/K. A latência não bloqueia o merge,
pois runners distintos não fornecem um ambiente controlado de desempenho.
O relatório atual é preservado por 14 dias, inclusive quando há regressão.

O comando retorna 0 quando passa, 1 quando encontra regressão e 2 para dados,
parâmetros ou referências incompatíveis. A comparação rejeita diferenças nos
hashes de dados, split, backend, chunking configurado, população de consultas
e matriz de estratégias/K. Alterar dados exige uma referência nova, revisada.

`--max-regression` aceita uma tolerância absoluta explícita para experimentos,
mas a CI não a utiliza. Não enfraqueça o gate nem sobrescreva a referência só
para tornar uma mudança verde. Uma troca intencional de qualidade entre métricas
exige resultados completos e justificativa no PR.

O relatório de resultados em
[CORPORATE_BENCHMARK_RESULTS.md](CORPORATE_BENCHMARK_RESULTS.md) registra a
baseline inicial, incluindo as configurações que tiveram desempenho pior.

## Estratégias adicionais: BM25 e RRF

O argumento `--strategies` seleciona uma matriz explícita. Sem esse argumento,
as quatro estratégias originais continuam sendo executadas; a referência
`baseline-hashing-test.json` não foi alterada.

```bash
uv run python -m enterprise_rag_system.benchmark --split test \
  --strategies bm25 rrf --backend hashing \
  --baseline data/benchmarks/corporate_pt_v1/baseline-bm25-rrf-hashing-test.json \
  --output benchmark-bm25-hashing.json
```

Para TF-IDF, use `--backend tfidf` e `baseline-bm25-rrf-tfidf-test.json`.
Todos os índices (incluindo BM25) são construídos antes da medição de consultas
e entram em `index_ms`; esse tempo pertence ao pipeline compartilhado, não
a um motor isolado. A inicialização do pipeline ainda cria o backend vetorial
configurado, mesmo quando o modo BM25 não o consulta.

BM25 retorna apenas chunks com correspondência de termos. RRF funde listas
de BM25 e similaridade vetorial positiva; escores zero/negativos não votam.
Empates são resolvidos por `chunk_id`, e escores novos não são arredondados
antes da ordenação. O bônus legado de título não é aplicado nessas ablações.

RRF usa a lista completa de candidatos, como a busca híbrida atual; não é uma
implementação de busca distribuída para milhões de chunks. TF-IDF é lexical,
não é embedding semântico multilíngue. A comparação exige o mesmo conjunto de
estratégias/K em ambos os relatórios e continua rejeitando mudanças de dados.

Na API, `RAG_RETRIEVAL_MODE=hybrid` continua incluindo o reranker legado.
Os modos `lexical` e `vector` da API também mantêm esse reranker, enquanto suas
ablações no benchmark usam `rerank=False`. Para comparar exatamente uma ablação
legada pela interface Python, informe `rerank=False` explicitamente.
