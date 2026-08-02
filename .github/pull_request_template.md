## Problema

<!-- Qual limitação, bug ou oportunidade motivou a mudança? -->

## Solução

<!-- O que mudou e quais decisões ou trade-offs foram feitos? -->

## Impacto

<!-- Efeito para usuários, desenvolvedores, API, dados ou operação. -->

## Validação

- [ ] `uv run ruff check .`
- [ ] `uv run mypy`
- [ ] `uv run pytest -q`
- [ ] `docker build --tag enterprise-rag-system:local .`
- [ ] Documentação atualizada quando necessário

## Evidência de recuperação

<!-- Para mudanças em chunking, retriever, fusão ou reranking, inclua o
comparativo definido em docs/BENCHMARKING.md. Caso não se aplique, explique. -->

| Configuração | Recall@1 | Recall@3 | MRR | Latência mediana | p95 |
|---|---:|---:|---:|---:|---:|
| baseline | N/A | N/A | N/A | N/A | N/A |
| candidato | N/A | N/A | N/A | N/A | N/A |

## Compatibilidade e segurança

- [ ] Não inclui credenciais, dados privados ou informações pessoais
- [ ] Mantém o núcleo funcional offline
- [ ] Mudanças incompatíveis de API/configuração estão documentadas
