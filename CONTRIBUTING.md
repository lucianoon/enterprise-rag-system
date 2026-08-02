# Contribuindo

Obrigado por considerar uma contribuição ao Enterprise RAG System.

## Antes de começar

- Para bugs e propostas, abra uma issue usando o template adequado.
- Para mudanças maiores de arquitetura ou contrato da API, descreva primeiro o problema e a abordagem.
- Não inclua documentos privados, credenciais, chaves de API ou dados pessoais em exemplos e testes.

## Ambiente de desenvolvimento

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lucianoon/enterprise-rag-system.git
cd enterprise-rag-system
uv sync --extra dev --extra extras
```

O núcleo e os testes padrão funcionam offline, sem chave de API.

## Fluxo de trabalho

1. Crie uma branch curta e descritiva.
2. Faça mudanças pequenas, com testes que demonstrem o comportamento.
3. Rode os mesmos gates da CI:

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
docker build --tag enterprise-rag-system:local .
```

Também é possível executar os três primeiros com `make check`.

4. Atualize a documentação quando alterar API, configuração, métricas ou trade-offs.
5. Abra um pull request explicando o problema, a solução, o impacto e a validação.

## Critérios de aceitação

Uma contribuição deve:

- preservar o funcionamento offline do núcleo;
- manter scores e decisões de recuperação observáveis;
- não reduzir Recall@K ou MRR sem documentar o trade-off;
- evitar dependência obrigatória de serviços externos;
- incluir testes determinísticos para comportamento novo;
- manter compatibilidade com os contratos Pydantic públicos ou registrar a quebra.

Para mudanças no retriever, chunking, fusão ou reranking, siga
[docs/BENCHMARKING.md](docs/BENCHMARKING.md) e inclua o comparativo antes/depois.

## Segurança

Não abra issues públicas para vulnerabilidades. Siga [SECURITY.md](SECURITY.md).
