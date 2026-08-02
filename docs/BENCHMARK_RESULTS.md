# Resultados do benchmark público

Resultados observados na demo pública do Enterprise RAG System em
**2 de agosto de 2026**, usando o dataset versionado `retrieval_v1`.

## Ambiente

- aplicação: Enterprise RAG System 0.3.0;
- endpoint: `https://enterprise-rag-demo.onrender.com/evaluate/batch`;
- plataforma: Render, plano gratuito;
- geração: determinística, conforme `render.yaml`;
- corpus: `data/sample/policies.jsonl`;
- dataset: `data/eval/retrieval_v1.jsonl`, com 10 consultas rotuladas.

O deploy não sobrescreve `RAG_EMBEDDING_BACKEND` nem `RAG_VECTOR_STORE`.
Portanto, pela configuração versionada e pelos defaults documentados, a demo
usa hashing determinístico e vector store em memória. Essa identificação é uma
inferência da configuração; a resposta do endpoint não expõe esses dois campos.

## Comandos

```bash
curl -X POST https://enterprise-rag-demo.onrender.com/evaluate/batch \
  -H "Content-Type: application/json" \
  -d '{"top_k": 1}'

curl -X POST https://enterprise-rag-demo.onrender.com/evaluate/batch \
  -H "Content-Type: application/json" \
  -d '{"top_k": 3}'
```

## Resultados observados

| Configuração | Consultas | Recall@K médio | MRR médio |
|---|---:|---:|---:|
| hashing + memória, K=1 | 10 | 1,000 | 1,000 |
| hashing + memória, K=3 | 10 | 1,000 | 1,000 |

Nas dez consultas, o documento relevante apareceu na primeira posição. Os
resultados completos por consulta continuam disponíveis na resposta do endpoint.

## Como interpretar corretamente

Este resultado confirma que a baseline versionada recupera corretamente o
documento rotulado para todas as dez consultas do corpus de demonstração. Ele
não comprova desempenho em documentos corporativos reais ou em outros domínios.

O corpus contém apenas três documentos (`policy_refunds`, `policy_security`
e `policy_sla`). Por isso:

- Recall@1 e MRR são os sinais mais discriminativos neste conjunto;
- Recall@3 tende a saturar porque K é igual ao número total de documentos;
- as consultas estão próximas do vocabulário das políticas;
- o conjunto é pequeno demais para estimar generalização;
- nenhuma afirmação de superioridade sobre outro sistema pode ser derivada
  destes números.

Latência não foi publicada nesta rodada porque o endpoint em lote não retorna
distribuição temporal e a execução pela interface pública não controla ruído de
rede, cold start ou infraestrutura compartilhada.

## Próxima avaliação

Para uma evidência mais forte:

1. aumentar o corpus e separar treino/ajuste de um conjunto de teste intocado;
2. incluir consultas adversariais, paráfrases e perguntas sem resposta;
3. comparar hashing, TF-IDF e embeddings densos;
4. medir mediana e p95 em execução local controlada;
5. publicar intervalos ou variação entre execuções;
6. registrar resultados automaticamente como artefato da CI.

O procedimento para futuras comparações está em
[BENCHMARKING.md](BENCHMARKING.md).
