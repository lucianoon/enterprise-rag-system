# Qdrant no fluxo do produto

O piloto agora suporta Qdrant como índice vetorial real, mantendo o SQLite para
os documentos, credenciais, histórico e cache de embeddings. A busca densa é
executada pelo Qdrant; o ranking lexical BM25 continua local e a fusão usa RRF.
`RAG_PRODUCT_VECTOR_STORE=qdrant` ativa o backend. O modo SQLite continua disponível
para desenvolvimento offline e compatibilidade.

## Executar

Com `OPENAI_API_KEY` em `.env.local` ignorado pelo Git:

```sh
docker compose --env-file .env.local -f compose.product.yml up -d --build
```

API: localhost:8002 (configurável com RAG_HTTP_PORT). Qdrant não publica portas
no host. Os volumes `product_state` e `qdrant_state` são persistentes. O compose
habilita busca híbrida, geração e reranking. O runtime local gerenciado nesta
sessão usa containers/volumes de nomes próprios, preservando seu acervo existente.
Não execute os dois runtimes na mesma porta.

## Indexação, migração e isolamento

`POST /index/sync` migra o acervo autorizado para Qdrant sem recalcular embeddings
já presentes no cache SQLite. Uploads novos confirmam gravação e presença dos
pontos no Qdrant antes de anunciar que o documento está pronto.

IDs de pontos incluem tenant, modelo e hash do conteúdo. A consulta recebe filtro
obrigatório por tenant e lista dos IDs dos trechos do snapshot autorizado atual.
Não basta filtrar depois da recuperação: a restrição vai na própria consulta ao
Qdrant. O campo tenant tem índice de payload. Versões antigas e documentos
excluídos podem continuar armazenados, mas não fazem parte dessa lista autorizada.
A coleção valida dimensão e distância; não é recriada destrutivamente se houver
incompatibilidade. Resultados são novamente conferidos contra a lista autorizada.

As escolhas seguem as referências oficiais:
- [Filtering](https://qdrant.tech/documentation/search/filtering/)
- [Payload indexing](https://qdrant.tech/documentation/manage-data/indexing/)
- [Query API](https://qdrant.tech/documentation/search/hybrid-queries/)

## Segunda ordenação

`RAG_PRODUCT_RERANK=true` usa o modelo configurado para ordenar até 30 candidatos
recuperados antes da resposta. Só aceita IDs únicos presentes nesses candidatos;
IDs restantes mantêm a ordem RRF. Falhas ou respostas inválidas preservam a ordem
híbrida e são registradas em `metadata.rerank_mode=rrf-fallback`. Essa etapa
adiciona uma chamada e latência; sua qualidade deve ser medida com o acervo real.

`metadata.vector_store` identifica o backend. Se a busca semântica falha, a API
sinaliza `bm25-semantic-fallback`, também visível na interface. `/ready` retorna
503 quando o Qdrant configurado está indisponível.

## Avaliação e limites

`scripts/evaluate_product_retrieval.py` executa 12 perguntas sintéticas sobre seis
documentos curtos, comparando BM25, híbrido e reranking com Recall@1, Recall@3 e
MRR@3. Usa embeddings reais e coleção temporária removida ao concluir.
Isso é um teste inicial de recuperação, não prova de superioridade no mercado,
correção das respostas, capacidade de abstenção ou desempenho sob carga.

Permanecem limites importantes: ingestão síncrona (5 MB/20 páginas/32 mil
caracteres), chunking fixo, consulta de presença de pontos por snapshot e ausência
de uma avaliação extensa com documentos reais. Antes de produção, medir qualidade,
custos e latência p95; testar backup/restauração dos dois volumes; adicionar fila
de ingestão e regras de retenção/purga. Embeddings cacheados permitem reconstruir
o índice Qdrant, mas não substituem uma política de backup testada.
