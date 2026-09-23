# Enterprise RAG System

*[English version](README.en.md)*

[![CI](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml/badge.svg)](https://github.com/lucianoon/enterprise-rag-system/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/lucianoon/enterprise-rag-system)

Motor de RAG em que **a qualidade da recuperação é o produto**, medido em
português. A maior parte das falhas de RAG é falha de recuperação: busca
semântica perde termos exatos (nomes de política, siglas, IDs), busca por
palavra-chave perde paráfrases, e sem métricas não dá para saber se uma resposta
ruim veio do gerador ou da lista ranqueada. Este repositório trata isso como
engenharia mensurável:

- **BM25 com normalização Unicode** (NFKD, sem acentos, casefold) num único
  analisador compartilhado por todas as pipelines;
- **vetores plugáveis**: hashing determinístico (CI), TF-IDF ou **embeddings
  multilíngues reais** (`multilingual-e5-small`, CPU, revisão fixada);
- **fusão por score ou RRF** e reranking heurístico ou **cross-encoder
  multilíngue** opcional;
- respostas com citações, scores expostos por estágio e endpoint de avaliação;
- **gates de regressão na CI**: benchmark versionado em português com hashes
  SHA-256 dos dados, referências congeladas e tolerância zero.

## Resultados medidos

`corporate_pt_v1`, split **test**: 30 documentos fictícios, 35 perguntas
respondíveis e 5 sem resposta, sem LLM. Medido em 22/09/2026 (CPU, Windows 11,
Python 3.12).

| Configuração | Recall@1 | Recall@5 | MRR@5 | nDCG@5 | p95@5 |
|---|---:|---:|---:|---:|---:|
| Híbrido + reranker, hashing (padrão da API) | 0,571 | 0,886 | 0,760 | 0,781 | < 1 ms |
| Lexical legado | 0,686 | 0,914 | 0,824 | 0,834 | < 1 ms |
| BM25 | 0,743 | 0,943 | 0,867 | 0,873 | < 1 ms |
| RRF: BM25 + TF-IDF | 0,700 | 0,943 | 0,846 | 0,855 | ~3 ms |
| Vetor `multilingual-e5-small` | 0,757 | **0,971** | 0,891 | 0,911 | ~56 ms |
| **RRF: BM25 + e5** | **0,843** | **0,971** | **0,943** | 0,945 | ~49 ms |
| BM25 + cross-encoder mMiniLM | 0,843 | 0,971 | 0,943 | **0,950** | ~1,6 s |

- Um embedding multilíngue real **supera o lexical** neste conjunto (antes, o
  melhor era o lexical legado com Recall@5 = 0,957); RRF é a fusão que preserva
  esse ganho. O cross-encoder empata com RRF + e5 a ~30x a latência.
- O padrão da API continua `hybrid` + hashing, sem dependências pesadas; a
  troca de padrão exige um conjunto de teste novo e independente.
- Corpus sintético, com autoria assistida por IA, e teste já conhecido: os
  números **não provam superioridade em dados reais**. Detalhes, dev e
  limitações: [embeddings multilíngues](docs/MULTILINGUAL_RETRIEVAL_RESULTS.md),
  [BM25/RRF](docs/BM25_RRF_RESULTS.md),
  [baseline e unificação do analisador](docs/CORPORATE_BENCHMARK_RESULTS.md),
  [protocolo](docs/BENCHMARKING.md).

```bash
uv run python -m enterprise_rag_system.benchmark --split test \
  --baseline data/benchmarks/corporate_pt_v1/baseline-hashing-test.json
# embeddings multilíngues (extra opcional, baixa ~0,5 GB):
uv sync --extra dev --extra extras --extra semantic
uv run python -m enterprise_rag_system.benchmark --split test \
  --backend sentence-transformer --strategies bm25 vector rrf
```

**[Demo ao vivo](https://enterprise-rag-demo.onrender.com/docs)** — API
interativa com o corpus de exemplo carregado; experimente o `POST /query` e o
`POST /evaluate/batch` direto do navegador (free tier: o primeiro acesso pode
levar ~1 min para acordar).

## Evidências rápidas

| Evidência | O que demonstra |
|---|---|
| Testes offline na CI | API, auth, recuperação, backends, concorrência e avaliação |
| Cobertura de linhas e branches, gate ≥ 80% | Verificação automatizada de cobertura |
| 30 documentos e 80 perguntas sintéticas em português | Baseline de recuperação com splits de desenvolvimento/teste |
| Matriz lexical/vetorial/híbrida e gate de qualidade | Recall, MRR, nDCG, precisão e latência reproduzíveis |
| Scores por estágio | Diagnóstico de falhas de recuperação |
| Hashing/TF-IDF/e5 multilíngue + cross-encoder | CI determinística e backend semântico real, com revisão de modelo fixada |
| Memória/Qdrant | Mesma interface do teste local à infraestrutura externa |
| Juiz heurístico ou LLM | Avaliação de fidelidade com fallback explícito |

**Baseline pública medida:** no dataset de demonstração `retrieval_v1` (10
consultas), a configuração hashing + memória obteve **Recall@1 = 1,000** e
**MRR = 1,000** em 2 de agosto de 2026. O corpus tem somente três documentos;
leia os [resultados e limitações](docs/BENCHMARK_RESULTS.md) antes de interpretar
ou comparar esses números.

Veja também a [direção do produto](docs/PRODUCT_DIRECTION.md).

## Problema

A maior parte das falhas de RAG é falha de recuperação. Busca puramente
semântica perde termos exatos que dominam consultas corporativas — nomes de
política, IDs, siglas, linguagem de compliance —, enquanto busca puramente por
palavra-chave perde paráfrases. E sem métricas de recuperação, não dá para saber
se uma resposta ruim veio do gerador ou da lista ranqueada que ele recebeu.

Este projeto trata a recuperação como o núcleo mensurável do sistema:

- fundir evidência lexical e vetorial em vez de apostar em um único sinal
- manter os componentes de score transparentes de ponta a ponta
- fazer da avaliação Recall@K / MRR uma operação de primeira classe da API, não
  um acessório

## Solução

Um pipeline compacto e totalmente tipado (`src/enterprise_rag_system/`):

| Estágio | Módulo | O que faz de fato |
|---|---|---|
| Ingestão | `ingestion.py` | Carrega documentos JSONL e os divide em chunks de tamanho fixo por contagem de palavras (padrão: 80 palavras) |
| Análise de texto | `tokenization.py` | Um único analisador (NFKD, remoção de acentos, casefold) para lexical, BM25, vetores, reranker, juiz e produto |
| Recuperação lexical | `retrieval.py`, `ranking.py` | Score IDF/log-TF legado e BM25 completo (`k1=1.2`, `b=0.75`) com listas invertidas |
| Embeddings | `embeddings.py` | Backends plugáveis: hashing determinístico (padrão offline/CI), TF-IDF (scikit-learn) ou vetores densos multilíngues (`multilingual-e5-small` fixado, extra `semantic`) |
| Vector store | `vector_store.py` | Backends plugáveis: busca por cosseno exata em memória ou um índice Qdrant real (o que o `docker compose` sobe) |
| Fusão | `retrieval.py`, `ranking.py` | Score híbrido ponderado `0.55 * lexical + 0.45 * vetorial` ou Reciprocal Rank Fusion |
| Reranking | `retrieval.py`, `cross_encoder.py` | Heurística de título (sobreposição + frase exata) ou cross-encoder multilíngue opcional sobre um pool de candidatos |
| Geração | `generation.py` | Claude sintetiza uma resposta fundamentada com citações entre colchetes; um gerador determinístico por template é o fallback offline/CI |
| Citações | `pipeline.py` | Toda resposta traz `doc_id` / `title` / `chunk_id` de cada trecho de apoio |
| Avaliação | `evaluation.py` | Recall@K e MRR por consulta rotulada, mais avaliação em lote sobre um dataset versionado com métricas agregadas |
| API | `api.py` | Serviço FastAPI: `/health`, `/query`, `/evaluate`, `/evaluate/batch`, auth opcional por API key |

As *interfaces* de recuperação (chunks entram, sai um `SearchResult` com
`lexical_score` / `vector_score` / `hybrid_score` / `rerank_score`) são o ponto
central: o mesmo pipeline roda contra os backends offline sem dependências ou
contra Qdrant + embeddings reais, escolhidos puramente por variáveis de
ambiente.

## Arquitetura

![Arquitetura](architecture.png)

```text
Documentos JSONL
      |
      v
Ingestão -> chunks por contagem de palavras
      |
      +----------------------+
      |                      |
      v                      v
Índice lexical (IDF)   Embedder -> Vector store
                       (hashing|tfidf|st)  (memory|qdrant)
      |                      |
      +----- fusão de scores +
      |   0.55*lex + 0.45*vet
      v
Reranker (sobreposição de título + bônus de frase exata)
      |
      v
Gerador de resposta (Claude, fallback determinístico) + citações
      |
      v
Avaliador (Recall@K, MRR)  <- consultas rotuladas via /evaluate
```

Mais detalhes em [docs/architecture.md](docs/architecture.md) (em inglês).

## Início rápido

Requer Python 3.12+.

```bash
git clone https://github.com/lucianoon/enterprise-rag-system.git
cd enterprise-rag-system
uv sync --extra dev              # núcleo: roda totalmente offline
uv sync --extra dev --extra extras   # opcional: qdrant-client + scikit-learn

uv run pytest -q                 # testes sem rede, sem chave de API
uv run ruff check . && uv run mypy   # mesmos gates que o CI aplica
uv run uvicorn enterprise_rag_system.api:app --port 8000
```

As versões vêm de `uv.lock`, então o ambiente local, o CI e a imagem Docker
resolvem exatamente as mesmas dependências.

Ou com make: `make install && make test && make dev`. Com Docker:
`docker compose up --build` sobe a API ligada a uma instância real do Qdrant
(`RAG_VECTOR_STORE=qdrant`, `RAG_EMBEDDING_BACKEND=tfidf`).

A API sobe já com o corpus de exemplo embutido (`data/sample/policies.jsonl` —
políticas de reembolso, segurança e SLA), então dá para consultar de imediato.

## Exemplos de uso

### Piloto com interface e persistência

`docker compose -f compose.product.yml up --build -d` sobe um modo explícito,
separado da API de demonstração: biblioteca de documentos em português,
revisões, restauração, permissões por tenant/documento aplicadas antes da busca,
credenciais revogáveis e consultas com fontes. O índice BM25 do produto usa o
mesmo núcleo e fica em cache por snapshot autorizado, invalidado a cada edição.
Veja o [guia de provisionamento, permissões e backup](docs/PRODUCT_PILOT.md).

### Perfil editorial configurável

O piloto aceita perfis de prompt versionados (`RAG_PRODUCT_PROFILE`), com hash
do prompt nos metadados de cada resposta. Um exemplo incluído é um assistente de
estudos inspirado em temas públicos de um pastor, que se apresenta sempre como
assistente de IA e não como a pessoa:
[configuração e fontes](docs/PASTORAL_PROFILE.md).

## Configuração

### Modos de geração de resposta

Defina `RAG_LLM_MODE` (veja `.env.example`):

- `auto` (padrão) — usa o modelo quando há backend configurado, senão o
  template determinístico
- `llm` — sempre chama o modelo (veja [Trocando de modelo ou de provedor](#trocando-de-modelo-ou-de-provedor))
- `deterministic` — sempre usa o template offline (é o que a CI roda)

Falhas do LLM, respostas vazias, recusas e respostas filtradas ativam o fallback
determinístico, com registro da falha no log. O campo `generation_mode` descreve
o caminho efetivamente usado naquela resposta: `llm` para texto gerado pelo
modelo, `deterministic-fallback` após falha do LLM e `deterministic` para o
template offline ou para a resposta sem contexto. Esse estado é por requisição,
inclusive quando consultas são executadas simultaneamente.

A interface Python `compose(question, results)` continua retornando texto.
Geradores que variam de modo por requisição podem implementar
`compose_with_metadata(question, results)`, retornando `GeneratedAnswer(text, mode)`.
Geradores personalizados existentes, com `compose` e `mode`, continuam aceitos.

### Trocando de modelo ou de provedor

O acesso ao LLM passa por uma porta única (`llm_client.py`) com dois backends
atrás da mesma interface — o gerador de resposta e o juiz de fidelidade usam os
dois igualmente:

| Variável | Valores |
|---|---|
| `RAG_LLM_BACKEND` | `auto` (padrão), `anthropic`, `openai` |
| `RAG_LLM_MODEL` | id do modelo; default `claude-opus-5` ou `gpt-4.1-mini` |
| `RAG_LLM_BASE_URL` | endpoint OpenAI-compatible (também aceita `OPENAI_BASE_URL`) |
| `RAG_LLM_API_KEY` | credencial; cai para `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` |

No modo `auto`, uma base URL seleciona `openai`, mesmo se uma chave Anthropic
também estiver exportada. Sem URL, a chave Anthropic tem preferência sobre a
chave OpenAI. A chave genérica `RAG_LLM_API_KEY` substitui a credencial do
provedor selecionado; quando configurada sozinha, mantém o padrão `anthropic`
por compatibilidade. Sem configuração, o pipeline usa o gerador determinístico.
`RAG_LLM_BACKEND=anthropic` ou `openai` sempre tem prioridade sobre a seleção
automática; use o valor explícito para manter Anthropic quando houver uma URL
compatível com OpenAI no ambiente.

```bash
# OpenRouter, Groq, Together, DeepInfra, Fireworks…
export RAG_LLM_BASE_URL=https://openrouter.ai/api/v1
export RAG_LLM_API_KEY=sk-or-v1-...
export RAG_LLM_MODEL=meta-llama/llama-3.3-70b-instruct

# Ollama local — sem credencial nenhuma
export RAG_LLM_BASE_URL=http://localhost:11434/v1
export RAG_LLM_MODEL=llama3.1
```

O backend OpenAI-compatible vem no extra `extras`.

### Backends de recuperação

Os dois estágios de recuperação são escolhidos por variáveis de ambiente (veja
`.env.example`):

- `RAG_EMBEDDING_BACKEND` — `hashing` (padrão: determinístico, zero
  dependências, estável entre processos), `tfidf` (scikit-learn, ajustado no
  corpus indexado), `sentence-transformer` (vetores densos multilíngues; padrão
  `intfloat/multilingual-e5-small` em revisão fixada, trocável por
  `RAG_ST_MODEL`/`RAG_ST_REVISION`; requer `--extra semantic`) ou `auto` (o
  melhor disponível).
- `RAG_VECTOR_STORE` — `memory` (padrão: busca exata por cosseno em processo) ou
  `qdrant` (usa `QDRANT_URL` e `COLLECTION_NAME`; o `docker compose` já liga
  isso).
- `RAG_API_KEY` — quando definida, `/query` e `/evaluate*` exigem o mesmo valor
  no cabeçalho `X-API-Key`. Sem ela, acesso aberto para desenvolvimento local.

### Corpus próprio e indexação preservada

Defina `RAG_DOCUMENTS_PATH` para um JSONL com `doc_id`, `title` e `text` por linha.
IDs precisam ser únicos e os campos não podem estar vazios. Um arquivo inválido
interrompe a inicialização antes da construção dos índices; sem a variável, a
API continua usando o exemplo. Configure também `RAG_EVAL_DATASET` com rótulos
do seu corpus para usar a avaliação em lote.

Qdrant agora cria uma geração física nova por indexação e só a usa depois de
confirmar os lotes e a contagem. Coleções existentes são preservadas.
`COLLECTION_NAME` é o prefixo dessas gerações, não um alias compartilhado.
**Gerações antigas consomem espaço e ainda exigem gestão operacional**; esta
mudança não adiciona ingestão incremental, multiempresa ou reutilização no restart.
Veja a [estratégia pesquisada, operação e limites](docs/SAFE_INGESTION_STRATEGY.md).

## Avaliação: Recall@K e MRR

A qualidade da recuperação é avaliada por consulta rotulada através da API (ou
pelo `RetrievalEvaluator` em código):

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
        "question": "What is the SLA for high priority support tickets?",
        "relevant_doc_ids": ["policy_sla"],
        "top_k": 3
      }'
```

Resposta (trecho):

```json
{
  "recall_at_k": 1.0,
  "mrr": 1.0,
  "retrieved_doc_ids": ["policy_sla", "policy_refunds", "policy_security"],
  "query": { "answer": "...", "citations": [...], "results": [...] }
}
```

Como ler os números:

- **Recall@K** — fração dos documentos rotulados como relevantes que aparecem em
  qualquer posição das top-K citações. `1.0` significa que tudo que era
  relevante foi recuperado; recall baixo significa que o gargalo é o retriever,
  não o gerador.
- **MRR** — rank recíproco do *primeiro* acerto relevante. `1.0` = documento
  relevante em primeiro lugar, `0.5` = segundo, `0.33` = terceiro, `0.0` =
  não apareceu. Recall alto com MRR baixo aponta para os pesos de
  fusão/ranqueamento ou para o reranker, não para a geração de candidatos.

Cada `SearchResult` também devolve seu `lexical_score`, `vector_score`,
`hybrid_score` e `rerank_score`, então dá para rastrear um ranqueamento ruim até
o estágio exato que o causou.

> O corpus de exemplo e o dataset de avaliação estão em inglês, então as
> consultas dos exemplos acima também estão. Aponte `RAG_EVAL_DATASET` para o
> seu próprio JSONL para avaliar um corpus em português.

### Avaliação em lote sobre um dataset versionado

Um dataset rotulado acompanha o repositório (`data/eval/retrieval_v1.jsonl` — 10
consultas contra o corpus de exemplo). Rode pela API ou pela CLI:

```bash
curl -X POST http://localhost:8000/evaluate/batch \
  -H "Content-Type: application/json" -d '{"top_k": 3}'

python -m enterprise_rag_system.evaluation --top-k 1     # ou: make eval
```

O relatório traz `mean_recall_at_k`, `mean_mrr` e métricas por consulta, então
uma mudança nos pesos de fusão, no chunking ou no reranker aparece como um diff
mensurável em vez de uma impressão. Aponte `RAG_EVAL_DATASET` para o seu próprio
JSONL (`{"query_id", "question", "relevant_doc_ids"}` por linha) para avaliar um
corpus real.

### Fidelidade da resposta

As métricas de recuperação param na lista ranqueada; `/evaluate/answer` julga o
que o *gerador* fez com ela — a fração de afirmações da resposta que estão
apoiadas nas passagens recuperadas, mais as afirmações sem apoio na íntegra:

```bash
curl -X POST http://localhost:8000/evaluate/answer \
  -H "Content-Type: application/json" \
  -d '{"question": "What must a refund request include?", "top_k": 3}'
```

Dois juízes compartilham a mesma interface, escolhidos por `RAG_JUDGE_MODE`
(`answer_eval.py`):

- `heuristic` (padrão) — contenção lexical sentença a sentença contra o
  contexto. Determinístico e offline: um proxy barato de groundedness que a CI
  consegue usar como gate, não uma verificação de implicação semântica.
- `llm` — Claude pontua a fidelidade e lista as afirmações sem apoio
  (`RAG_JUDGE_MODEL` sobrescreve o modelo). Cai no juiz heurístico em caso de
  erro de API, reportado como `judge_mode: "heuristic-fallback"`.

### Trade-offs de recuperação, explicitados

- **Pesos de fusão** (`0.55` lexical / `0.45` vetorial) favorecem levemente a
  terminologia corporativa exata sobre o casamento por paráfrase — ajuste por
  corpus e reconfira o MRR.
- **Pool de candidatos**: o pipeline recupera `2 * top_k` candidatos antes do
  reranking; é um botão de recall vs. latência.
- **Embeddings hasheados por padrão** trocam qualidade semântica por
  determinismo e zero infraestrutura — ideal para CI e para isolar o
  comportamento lexical vs. vetorial; os backends `tfidf` e
  `sentence-transformer` oferecem semântica de produção atrás da mesma
  interface.
- **O reranker padrão** é uma heurística barata (sobreposição de título + frase
  exata). O cross-encoder multilíngue opcional
  (`RAGPipeline(chunks, reranker=CrossEncoderReranker(), rerank_pool=20)`) não
  melhorou Recall/MRR sobre RRF + e5 no benchmark e custa ~1,6 s por consulta em CPU.

## API

| Endpoint | Método | Descrição |
|---|---|---|
| `/health` | GET | Verificação de liveness (sempre aberto) |
| `/query` | POST | `{question, top_k}` → resposta fundamentada, citações, scores por estágio, metadados de latência |
| `/evaluate` | POST | `{question, relevant_doc_ids, top_k}` → Recall@K, MRR, IDs recuperados, resposta completa da consulta |
| `/evaluate/batch` | POST | `{top_k}` → Recall@K / MRR agregados sobre o dataset de avaliação versionado |
| `/evaluate/answer` | POST | `{question, top_k}` → responde a pergunta e então julga a fidelidade da resposta contra o próprio contexto recuperado |

Quando `RAG_API_KEY` está definida, todos os endpoints exceto `/health` exigem o
cabeçalho `X-API-Key`.

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What does the refund policy require?","top_k":3}'
```

Os metadados da resposta incluem `query_id`, `latency_ms`, `top_k`,
`result_count` e `generation_mode`. Todos os contratos de request/response são
modelos Pydantic em
[`models.py`](src/enterprise_rag_system/models.py).

## Testes

```bash
pytest -q
```

Os testes cobrem os endpoints da API (incluindo auth e erros de validação),
unidades de recuperação, todos os backends de embedding e de vector store (o
Qdrant roda em modo `:memory:`), avaliação em lote e o comportamento de seleção
e fallback do gerador. Rodam inteiramente offline — os caminhos determinísticos
de embedding e de geração significam que a CI não precisa de segredos, que é
exatamente como o [`.github/workflows/ci.yml`](.github/workflows/ci.yml) os
executa.

## Qualidade e contribuição

Mudanças no retriever, chunking, fusão de scores ou reranking devem trazer um
comparativo reproduzível. O [protocolo de benchmark](docs/BENCHMARKING.md)
define dataset, comandos, métricas e o formato de relatório — sem publicar
números que não tenham sido executados.

Contribuições são bem-vindas. Consulte [CONTRIBUTING.md](CONTRIBUTING.md); os
templates de issue coletam ambiente e reprodução, e o template de pull request
exige os mesmos gates da CI e evidência de regressão para mudanças de recuperação.

## Roadmap

- Stemming leve para português (RSLP) avaliado no dev
- Conjunto de teste independente para decidir RRF + e5 como padrão
- Avaliação de qualidade de resposta em lote (fidelidade agregada sobre o
  dataset de avaliação)
- Indexação incremental em vez de reindexação completa na inicialização

## Licença

[MIT](LICENSE) — © 2026 Luciano de Oliveira Nunes.
