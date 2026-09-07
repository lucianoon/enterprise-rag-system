# BM25 e RRF: comparação de recuperação em português

## Hipótese e decisão

A tokenização legada divide palavras acentuadas (`aprovação` vira fragmentos),
o score lexical não normaliza comprimento, e a fusão soma scores de escalas
diferentes. Avaliamos duas alternativas, sem alterar os rótulos ou corpus:

- BM25: título + texto, normalização Unicode NFKD, remoção de marcas de acento,
  casefold, sem stemming ou stopwords; `k1=1.2`, `b=0.75`, IDF positivo.
- RRF: BM25 + vetor, pesos iguais, constante 60, ranks começando em 1.
  Só candidatos com score positivo votam; empate por ID do chunk.

Parâmetros fixados por convenções da literatura antes de executar os ensaios,
sem busca de hiperparâmetros. Desenvolvimento primeiro, teste depois; o teste
já era conhecido da etapa anterior e **não é uma avaliação cega independente**.
Não podemos atribuir o ganho isoladamente ao BM25 ou à normalização de acentos:
ambas as mudanças fazem parte da configuração avaliada.

BM25 fica disponível via `RAG_RETRIEVAL_MODE=bm25`. O padrão da API permanece
`hybrid`, pois o teste é pequeno, sintético e sem anotação humana independente.
RRF permanece experimental: a fusão por posições não corrige um vetor ruim.

## Teste: 35 perguntas respondíveis e cinco sem resposta

Recall é macro por pergunta (inclui cinco perguntas com duas fontes); não é
a porcentagem de respostas corretas. K conta chunks, como no benchmark original.

| Estratégia | Recall@1 | Recall@3 | Recall@5 | MRR@5 | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| Lexical legado | 0.5857 | 0.8571 | 0.9571 | 0.7743 | 0.8080 |
| Híbrido + reranker legado | 0.5857 | 0.8429 | 0.8429 | 0.7286 | 0.7482 |
| BM25 | 0.7429 | 0.8857 | 0.9429 | 0.8667 | 0.8727 |
| RRF + hashing | 0.3143 | 0.6000 | 0.6857 | 0.4948 | 0.5305 |
| RRF + TF-IDF | 0.7000 | 0.8857 | 0.9429 | 0.8414 | 0.8493 |

BM25 melhora a ordem dos resultados frente ao híbrido atual, mas não vence em
todas as métricas: lexical legado mantém Recall@5 ligeiramente maior (0,9571
contra 0,9429). RRF + hashing piora; RRF + TF-IDF não supera BM25 nesta amostra.
A CI preserva essas configurações como referências distintas, sem apagar os
resultados desfavoráveis ou reduzir a exigência da referência legada.

## Desenvolvimento (35 perguntas respondíveis)

| Estratégia | Recall@1 | Recall@3 | Recall@5 | MRR@5 |
|---|---:|---:|---:|---:|
| lexical / hashing | 0.6857 | 0.8143 | 0.8857 | 0.7986 |
| hybrid-rerank / hashing | 0.7000 | 0.8000 | 0.8571 | 0.7986 |
| bm25 / hashing | 0.7000 | 0.9143 | 0.9429 | 0.8405 |
| rrf / hashing | 0.4857 | 0.7143 | 0.7714 | 0.6390 |
| hybrid-rerank / tfidf | 0.7286 | 0.8286 | 0.8571 | 0.8010 |
| rrf / tfidf | 0.7000 | 0.9143 | 0.9429 | 0.8405 |

## Variabilidade descritiva

Bootstrap pareado por pergunta respondível, 10.000 reamostragens, seed 20260907,
percentis 2,5/97,5% (posições 249/9749 do vetor ordenado). A tabela mostra
BM25 menos híbrido + reranker. Os intervalos assumem perguntas independentes;
como há documentos e temas compartilhados, **não demonstram generalização**.

| Métrica | Diferença média | Intervalo descritivo 95% |
|---|---:|---:|
| recall@1 | +0.1571 | [+0.0286, +0.2857] |
| recall@5 | +0.1000 | [+0.0000, +0.2143] |
| mrr@5 | +0.1381 | [+0.0429, +0.2429] |

## Reproduzir

```bash
uv sync --extra dev --extra extras --locked
uv run python -m enterprise_rag_system.benchmark --split dev \
  --strategies lexical hybrid-rerank bm25 rrf --output benchmark-report.json
uv run python -m enterprise_rag_system.benchmark --split test \
  --strategies bm25 rrf --backend hashing \
  --baseline data/benchmarks/corporate_pt_v1/baseline-bm25-rrf-hashing-test.json \
  --output benchmark-bm25-hashing.json
uv run python -m enterprise_rag_system.benchmark --split test \
  --strategies bm25 rrf --backend tfidf \
  --baseline data/benchmarks/corporate_pt_v1/baseline-bm25-rrf-tfidf-test.json \
  --output benchmark-bm25-tfidf.json
RAG_RETRIEVAL_MODE=bm25 uv run uvicorn enterprise_rag_system.api:app
```

A variável é lida na construção da API e exige reinicialização. O benchmark
seleciona estratégias explicitamente e ignora essa variável. Na interface Python:
`RAGPipeline(chunks, retrieval_mode="bm25")` ou
`pipeline.retrieve(question, mode="bm25", rerank=False)`.

As duas referências JSON guardam todos os rankings, ambiente e hashes. Os
relatórios completos são publicados pela CI. O índice BM25 é construído junto
com os índices existentes, incluído no tempo de indexação. Os números abaixo
são locais e não representam capacidade em produção ou corpus grande.

| Backend | Indexação do pipeline (ms) | BM25 p95@5 (ms) | RRF p95@5 (ms) |
|---|---:|---:|---:|
| hashing | 5.549 | 0.083 | 0.209 |
| tfidf | 1218.004 | 0.083 | 3.212 |

Ambiente: Python 3.12.13, macOS-26.6.2-arm64-arm-64bit;
TF-IDF scikit-learn 1.9.0, NumPy 2.5.1.

Corpus SHA-256: `060423af4c6eff89c7cde4f9d6fefb8fd86665f21f6e14cf539dfe4df0c755d9`.
Queries SHA-256: `e513ec36756e386602e27342329abd2ede1871bc2d0afcc23cb183a1d91dd125`.
Source SHA-256: `458fb9862cd4f775713635b72724adb126ba32e30bc23987cee462abd4f71b68`.

## Limitações e próximo critério

- Perguntas sem resposta são separadas das métricas de relevância. Remover
  candidatos de score zero não resolve abstenção: termos comuns ainda retornam
  documentos. Não há medida nova de alucinação ou correção de respostas.
- As citações e a geração de respostas não foram avaliadas por este ensaio.
- TF-IDF é um vetor lexical; não substitui avaliação de embeddings multilíngues.
- RRF usa rankings completos em memória; falta avaliar candidate pools e escala.
- A normalização pode colapsar palavras distintas; é intencional nesta opção e
  precisa ser validada em cada domínio. Não há stemming nem expansão de sinônimos.
- Promover um novo padrão exige corpus autorizado maior, anotação independente,
  análise por domínio e medições de latência/custo. Nenhum score aqui prova
  superioridade sobre outro produto.

## Fontes das fórmulas

[Apache Lucene BM25Similarity](https://lucene.apache.org/core/9_12_3/core/org/apache/lucene/search/similarities/BM25Similarity.html):
parâmetros e IDF. A implementação usa o fator constante `(k1+1)` no numerador;
não pretende reproduzir as normas de campo ou o analisador do Lucene.

[Cormack, Clarke e Büttcher, SIGIR 2009](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf):
fusão recíproca por posição. Esta avaliação usa o corpus sintético local,
sem equivalência de resultados com os conjuntos do artigo.

### Reproduzir os intervalos descritivos

Execute este trecho Python na raiz do repositório (somente biblioteca padrão):

```python
import json
import random
from pathlib import Path
from statistics import mean

root = Path('data/benchmarks/corporate_pt_v1')
before = json.loads((root / 'baseline-hashing-test.json').read_text())
after = json.loads((root / 'baseline-bm25-rrf-hashing-test.json').read_text())

def values(report, strategy, cutoff, metric):
    row = next(r for r in report['rows']
               if r['strategy'] == strategy and r['top_k'] == cutoff)
    return {r['query_id']: r['metrics'][metric]
            for r in row['per_query'] if r['metrics'] is not None}

for metric, cutoff in [('recall', 1), ('recall', 5), ('mrr', 5)]:
    old = values(before, 'hybrid-rerank', cutoff, metric)
    new = values(after, 'bm25', cutoff, metric)
    assert old.keys() == new.keys()
    differences = [new[key] - old[key] for key in sorted(old)]
    rng = random.Random(20260907)
    samples = sorted(mean(rng.choices(differences, k=len(differences)))
                     for _ in range(10000))
    print(metric, cutoff, mean(differences), samples[249], samples[9749])
```
