# Baseline corporativa em português

Medições locais do conjunto sintético `corporate_pt_v1`, em 7 de setembro de 2026. Não representam produção, avaliação humana independente ou comparação com concorrentes.

## Protocolo

30 documentos, 40 perguntas por split: 35 respondíveis e 5 sem resposta. As médias de qualidade usam as 35 respondíveis. K conta chunks, com ganho zero para documentos repetidos. Cinco repetições medidas por consulta/configuração, após um aquecimento; medianas e p95 não incluem indexação nem geração. O padrão da busca não foi ajustado para este conjunto.

O score lexical é a fórmula IDF/log-TF existente, não BM25 completo. Hashing é uma representação lexical de 48 dimensões, não um modelo semântico. TF-IDF também não equivale a embeddings densos multilíngues.

## Ambiente e dados

- Python: 3.12.13; plataforma: macOS-26.6.2-arm64-arm-64bit.
- Pydantic: 2.13.5; scikit-learn: 1.9.0; NumPy: 2.5.1.
- Corpus SHA-256: `060423af4c6eff89c7cde4f9d6fefb8fd86665f21f6e14cf539dfe4df0c755d9`.
- Queries SHA-256: `e513ec36756e386602e27342329abd2ede1871bc2d0afcc23cb183a1d91dd125`.
- Código-fonte SHA-256: `2b7b60a062fbf9fc4cd7270f9e567e634418a50f9f31296cbdba952003a63ffb`.

A referência [JSON de teste](../data/benchmarks/corporate_pt_v1/baseline-hashing-test.json) inclui todas as classificações por pergunta, horários e metadados. Os comandos de reprodução estão no [protocolo](BENCHMARKING.md).

## dev — hashing

Dimensões vetoriais: 48. Cada ablação usa o mesmo corpus e o mesmo embedder desta seção.

| Estratégia | K | Recall | Precisão | MRR | nDCG | Mediana ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 1 | 0.6857 | 0.7429 | 0.7429 | 0.7429 | 0.187 | 0.203 |
| lexical | 3 | 0.8143 | 0.3143 | 0.7857 | 0.7854 | 0.184 | 0.209 |
| lexical | 5 | 0.8857 | 0.2057 | 0.7986 | 0.8163 | 0.183 | 0.198 |
| vector | 1 | 0.1857 | 0.2000 | 0.2000 | 0.2000 | 0.154 | 0.166 |
| vector | 3 | 0.5000 | 0.1905 | 0.3571 | 0.3819 | 0.152 | 0.165 |
| vector | 5 | 0.5857 | 0.1314 | 0.3786 | 0.4188 | 0.152 | 0.163 |
| hybrid | 1 | 0.6571 | 0.7143 | 0.7143 | 0.7143 | 0.285 | 0.309 |
| hybrid | 3 | 0.8143 | 0.3143 | 0.7714 | 0.7748 | 0.285 | 0.308 |
| hybrid | 5 | 0.9143 | 0.2114 | 0.7914 | 0.8180 | 0.289 | 0.311 |
| hybrid-rerank | 1 | 0.7000 | 0.7714 | 0.7714 | 0.7714 | 0.295 | 0.317 |
| hybrid-rerank | 3 | 0.8000 | 0.3143 | 0.7857 | 0.7872 | 0.302 | 0.325 |
| hybrid-rerank | 5 | 0.8571 | 0.2000 | 0.7986 | 0.8105 | 0.321 | 0.354 |

## dev — tfidf

Dimensões vetoriais: 2048. Cada ablação usa o mesmo corpus e o mesmo embedder desta seção.

| Estratégia | K | Recall | Precisão | MRR | nDCG | Mediana ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 1 | 0.6857 | 0.7429 | 0.7429 | 0.7429 | 0.185 | 0.202 |
| lexical | 3 | 0.8143 | 0.3143 | 0.7857 | 0.7854 | 0.183 | 0.198 |
| lexical | 5 | 0.8857 | 0.2057 | 0.7986 | 0.8163 | 0.184 | 0.200 |
| vector | 1 | 0.7286 | 0.8000 | 0.8000 | 0.8000 | 3.063 | 3.283 |
| vector | 3 | 0.9000 | 0.3429 | 0.8381 | 0.8461 | 3.058 | 3.093 |
| vector | 5 | 0.9429 | 0.2171 | 0.8438 | 0.8647 | 3.061 | 3.085 |
| hybrid | 1 | 0.6857 | 0.7429 | 0.7429 | 0.7429 | 3.207 | 3.298 |
| hybrid | 3 | 0.8143 | 0.3143 | 0.7857 | 0.7854 | 3.274 | 3.318 |
| hybrid | 5 | 0.9143 | 0.2114 | 0.8043 | 0.8273 | 3.256 | 3.296 |
| hybrid-rerank | 1 | 0.7286 | 0.8000 | 0.8000 | 0.8000 | 3.217 | 3.298 |
| hybrid-rerank | 3 | 0.8286 | 0.3238 | 0.7952 | 0.8037 | 3.255 | 3.326 |
| hybrid-rerank | 5 | 0.8571 | 0.2000 | 0.8010 | 0.8148 | 3.299 | 3.448 |

## test — hashing

Dimensões vetoriais: 48. Cada ablação usa o mesmo corpus e o mesmo embedder desta seção.

| Estratégia | K | Recall | Precisão | MRR | nDCG | Mediana ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| lexical | 1 | 0.5857 | 0.6571 | 0.6571 | 0.6571 | 0.188 | 0.206 |
| lexical | 3 | 0.8571 | 0.3238 | 0.7571 | 0.7680 | 0.189 | 0.208 |
| lexical | 5 | 0.9571 | 0.2171 | 0.7743 | 0.8080 | 0.188 | 0.206 |
| vector | 1 | 0.1286 | 0.1714 | 0.1714 | 0.1714 | 0.157 | 0.161 |
| vector | 3 | 0.2857 | 0.1143 | 0.2286 | 0.2282 | 0.157 | 0.162 |
| vector | 5 | 0.3857 | 0.0914 | 0.2557 | 0.2714 | 0.157 | 0.161 |
| hybrid | 1 | 0.5857 | 0.6571 | 0.6571 | 0.6571 | 0.294 | 0.316 |
| hybrid | 3 | 0.8429 | 0.3238 | 0.7381 | 0.7550 | 0.295 | 0.316 |
| hybrid | 5 | 0.9000 | 0.2057 | 0.7495 | 0.7771 | 0.294 | 0.313 |
| hybrid-rerank | 1 | 0.5857 | 0.6571 | 0.6571 | 0.6571 | 0.305 | 0.327 |
| hybrid-rerank | 3 | 0.8429 | 0.3238 | 0.7286 | 0.7482 | 0.318 | 0.341 |
| hybrid-rerank | 5 | 0.8429 | 0.1943 | 0.7286 | 0.7482 | 0.330 | 0.356 |

## O que os resultados mostram

- No teste, a busca lexical alcança Recall@5 de 0,9571; a configuração padrão híbrida com reranking alcança 0,8429. A complexidade adicional não melhora todas as métricas neste conjunto.
- O componente vetorial por hashing, isolado, é fraco: Recall@5 de 0,3857 no teste. Não deve ser apresentado como busca semântica de alta qualidade.
- No desenvolvimento, o vetor TF-IDF alcança Recall@5 de 0,9429; isso justifica novos experimentos, mas não prova generalização nem determina automaticamente o backend de produção.
- Todas as configurações devolvem candidatos para todas as perguntas sem resposta (`unanswerable_return_rate = 1,0`). Essa é uma limitação do retriever atual, não uma medição de alucinação do gerador.

## Limitações e próximos experimentos

O corpus e os rótulos foram escritos com assistência de IA, sem avaliação humana independente. Os splits compartilham documentos e têm distribuições de perguntas diferentes. As latências são de um corpus pequeno, em uma máquina sem carga controlada, e não devem ser extrapoladas para produção.

A baseline de teste agora é conhecida e usada como regressão. Não a trate como teste cego em novos ciclos de ajuste. Próximos experimentos devem usar dev para selecionar hipóteses e um conjunto independente para validar ganhos: BM25 completo, normalização linguística, embeddings multilíngues e fusão por ranking, além de uma avaliação separada de abstenção e citações.
