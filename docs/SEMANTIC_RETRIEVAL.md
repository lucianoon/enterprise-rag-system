# Busca semântica do produto

O backend Qdrant e o reranking estão descritos em [QDRANT_PRODUCT.md](QDRANT_PRODUCT.md).
O restante desta página descreve o modo SQLite de compatibilidade.

Defina `RAG_PRODUCT_RETRIEVAL=hybrid` e disponibilize `OPENAI_API_KEY` no
container. O padrão sem essa opção continua BM25, para execução offline.

A integração usa `text-embedding-3-small`, 1536 dimensões. Vetores normalizados
são persistidos em `semantic_vectors`, no mesmo SQLite e volume dos documentos.
A busca vetorial é exata, em memória, sobre vetores carregados do SQLite após
filtragem de permissões; não usa Qdrant nem índice ANN nesta versão do piloto.

Salvar grava primeiro o documento e tenta indexar o acervo acessível. A resposta
inclui `indexing: ready|pending`. Falhas não descartam a edição. A próxima consulta
repete a indexação pendente. `POST /index/sync` permite que administradores
indexem os documentos existentes aos quais têm acesso sem alterar versões.

Os vetores são identificados por tenant, modelo e hash do título/texto do trecho.
Reinícios reutilizam o cache. Edições geram vetores novos para conteúdos alterados;
restaurações reutilizam vetores já existentes ou os geram na próxima consulta.
Vetores antigos permanecem como cache local, mas não participam de buscas quando
não correspondem ao snapshot atual autorizado (incluindo exclusões). A exclusão
lógica não é uma purga de dados históricos ou vetores.

Cada pergunta recebe seu próprio embedding. A seleção combina rankings BM25 e
similaridade por Reciprocal Rank Fusion (constante 60, até 50 candidatos de cada
ranking). Similaridade mínima 0,3 é uma heurística inicial, ainda sem calibração
para o acervo do cliente. A estrutura das citações continua validada, sem garantia
automática de fidelidade factual.

`metadata.retrieval_mode` informa `hybrid`, `bm25` ou
`bm25-semantic-fallback`. Falhas do provedor mantêm busca lexical operacional.
O texto dos documentos e perguntas é enviado à OpenAI para gerar embeddings;
a chave permanece no ambiente local e não é gravada no índice.

Referência: https://developers.openai.com/api/docs/models/text-embedding-3-small
