# Direção do produto: evidência antes de liderança

## Hipótese de nicho

RAG para consultar políticas e documentos internos em português, com fontes
verificáveis e uma opção de execução local. Este foco é uma hipótese inicial;
a validação com usuários pode mudar idioma, domínio e requisitos de operação.

O objetivo é responder perguntas corporativas com evidência suficiente, mostrar
quando não há suporte documental e permitir auditoria do caminho da resposta.
Não há evidência suficiente para afirmar que o projeto é o melhor do nicho.

## Etapas e critérios de conclusão

### 1. Medir a qualidade atual

- Comparar lexical, vetorial, híbrido e híbrido com reranking no mesmo corpus.
- Publicar métricas por pergunta, rótulos, hashes de dados e ambiente de execução.
- Separar perguntas sem resposta das médias de recuperação.
- Bloquear regressões de qualidade na CI e preservar o relatório como artefato.
- Manter o conjunto sintético claramente identificado e os limites documentados.

Esta etapa está implementada pelo benchmark `corporate_pt_v1`. Seus resultados
são uma baseline de engenharia; não são prova de superioridade comercial.

### 2. Melhorar recuperação em português

- Acrescentar uma baseline BM25 completa, distinta do score lexical atual.
- Comparar embeddings multilíngues e rerankers no desenvolvimento, registrando
  memória, tempo de indexação, latência e qualidade no mesmo hardware.
- Avaliar normalização de acentos, chunking por estrutura e fusão por ranking.
- Promover uma configuração somente depois de declarar a hipótese, congelar
  parâmetros e mostrar o efeito em um conjunto independente de teste.
- Usar avaliação pareada e intervalos de confiança para separar melhorias
  consistentes de ganhos de poucas perguntas. Não escolher apenas a melhor métrica.

BM25 com normalização de acentos e RRF estão implementados como opções
explícitas, com [resultados publicados](BM25_RRF_RESULTS.md). Ainda faltam
embeddings multilíngues, validação independente e decisão sobre o padrão.

### 3. Respostas verificáveis e abstenção

- Validar se cada marcador de citação aponta para uma fonte recuperada válida.
- Medir suporte de afirmações e utilidade com anotação humana independente.
- Calibrar abstinência em desenvolvimento e medir falsos positivos e negativos
  em teste, incluindo perguntas com premissas falsas e documentos conflitantes.
- Testar explicitamente instruções maliciosas dentro dos documentos.
- Não tratar similaridade lexical do juiz heurístico como prova de veracidade.

### 4. Operação corporativa

- Definir um modelo de autorização e garantir isolamento entre coleções e usuários.
- Propagar revogação de acesso à recuperação e a caches, com testes negativos.
- Separar ingestão e inicialização da API; atualizar índices sem apagá-los a cada start.
- Medir p50/p95/p99 sob carga em corpus maior, com orçamento de recursos publicado.
- Instrumentar tempos por etapa, falhas, fallback e uso dos provedores, sem
  registrar documentos ou credenciais sensíveis por padrão.
- Documentar backup, restauração, migração de índices e limites de requisição.

A indexação Qdrant agora preserva gerações anteriores e só ativa uma nova
após confirmação dos lotes e da contagem. A API aceita um corpus JSONL
configurado. A [decisão e seus limites](SAFE_INGESTION_STRATEGY.md) estão
documentados. O [modo piloto dedicado](PRODUCT_PILOT.md) acrescenta registro
SQLite durável, ACL antes da busca, histórico, backup e UI. Esse modo usa BM25
e não reindexa Qdrant ao iniciar. Retenção/expurgo, integração das gerações
vetoriais ao registro e medição sob carga continuam pendentes.

### 5. Demonstrar valor em um piloto

- Selecionar usuários e tarefas reais antes de escolher um concorrente de comparação.
- Obter um corpus autorizado e rótulos humanos, com critérios de aceite acordados.
- Comparar com busca lexical e uma solução alternativa configurada de forma justa.
- Medir tempo para encontrar respostas, qualidade das fontes, custo e satisfação.
- Publicar metodologia e resultados reproduzíveis; restringir qualquer alegação
  de superioridade ao domínio, orçamento e condições efetivamente avaliados.

## Referências metodológicas

[BEIR](https://github.com/beir-cellar/beir) fornece um exemplo de avaliação
heterogênea de recuperação e métricas como Recall, MRR e nDCG. Usar as mesmas
famílias de métricas não torna o conjunto sintético deste projeto equivalente
ao BEIR nem permite comparar números entre corpora diferentes.
