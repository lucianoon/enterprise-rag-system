# Contribuindo

Obrigado por considerar uma contribuição ao Enterprise RAG System.

## Antes de começar

- Para bugs e propostas, abra uma issue usando o template adequado.
- Para mudanças maiores de arquitetura ou contrato da API, descreva primeiro o problema e a abordagem.
- Não inclua documentos privados, credenciais, chaves de API ou dados pessoais em exemplos e testes.

## Ambiente de desenvolvimento

Requer Python 3.12+, [uv](https://docs.astral.sh/uv/) e a CLI do Entire instalada
e autenticada, com acesso ao repositório. O `origin` principal fica no Entire:

```bash
git clone entire://aws-sa-east-1.entire.io/et/enterprise-rag-system/enterprise-rag-system
cd enterprise-rag-system
uv sync --extra dev --extra extras --locked
```

O núcleo e os testes padrão funcionam offline, sem chave de API.

As configurações compartilhadas ficam em `.entire/settings.json` e
`.codex/hooks.json`. Os hooks Git de `.git/hooks` e as aprovações do Codex são
locais: cada clone precisa concluir a instalação. Para usar Codex, execute:

```bash
entire enable --agent codex
entire status
```

No Codex, abra `/hooks`, revise e aprove os hooks do Entire; depois inicie uma
nova sessão no repositório. Logs, metadados locais, arquivos temporários e
`settings.local.json` ficam fora do versionamento pelo `.entire/.gitignore`.

Em checkouts que também usam GitHub, o remoto `github` aponta para
`https://github.com/lucianoon/enterprise-rag-system.git`. Confira os destinos com
`git remote -v`; um clone novo do Entire cria apenas o `origin`. Para adicionar
o remoto GitHub, caso ainda não exista:

```bash
git remote add github https://github.com/lucianoon/enterprise-rag-system.git
```

## Fluxo de trabalho com Entire

### 1. Prepare a branch e confira a captura da sessão

Com o diretório de trabalho limpo, atualize a base e crie uma branch curta e
descritiva:

```bash
git switch main
git pull --ff-only origin main
git switch -c docs/fluxo-entire
entire agent-help
entire status
```

Para trabalho com agentes, confira se o Entire está habilitado e se a integração
do agente está ativa. Na sessão do agente, consulte:

```bash
entire session current --json
```

O campo `resolution` indica a origem da sessão encontrada: `caller-env` ou
`ancestry` identificam a sessão que executou o comando; outros valores podem
ser apenas uma sessão recente. Não trate esse fallback como prova de captura da
sessão atual. Se houver hooks pendentes ou integração ausente, peça ao responsável
para concluir a configuração e inicie uma nova sessão antes de depender da captura.

A CLI instalada é a referência para os comandos e suas opções: consulte
`entire agent-help <comando>` e, quando necessário,
`entire agent-help <comando> <subcomando>`.

### 2. Implemente e valide

Faça mudanças pequenas, com testes determinísticos que demonstrem comportamento
novo. Atualize a documentação quando alterar API, configuração, métricas ou
trade-offs. Para recuperar contexto já registrado, use, por exemplo:

```bash
entire search "fusão de scores" --limit 5 --compact
entire why src/enterprise_rag_system/api.py:1
```

A busca remota depende de autenticação, sincronização e indexação; ela não
substitui a inspeção das alterações locais com `git diff`.

Antes do commit, execute os gates básicos:

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
docker build --tag enterprise-rag-system:local .
```

Também é possível executar os três primeiros com `make check`.

A [CI no GitHub](.github/workflows/ci.yml) também verifica cobertura, benchmarks
de recuperação, integração com Qdrant e smoke tests Docker. Esses checks continuam
necessários para a revisão; registre quais validações foram executadas e eventuais
limitações do ambiente.

### 3. Revise e faça o commit local

Revise o diff e selecione somente os arquivos da contribuição para o staging.
`git add -p` permite revisar trechos de arquivos rastreados; para arquivos novos,
use `git add --` seguido dos caminhos específicos.

```bash
git diff --check
git diff
git add -p
git diff --cached
git commit -m "docs: atualizar fluxo de contribuição"
```

Com a integração ativa, o commit Git captura automaticamente a sessão como um
checkpoint. Não é necessário criar checkpoints manualmente. Após o commit,
confirme o vínculo e consulte o contexto:

```bash
git log -1 --format=full
entire checkpoint list --json
entire checkpoint explain --commit HEAD --short
```

Confira o trailer `Entire-Checkpoint` e se o checkpoint corresponde ao commit.
Se não houver vínculo, registre a ausência e verifique `entire status` antes de
afirmar que a contribuição tem rastreabilidade de sessão. Prompts e respostas
também fazem parte do contexto capturado: não inclua segredos ou dados privados.

### 4. Publique para revisão

O commit acima é local. Para validar a branch no GitHub Actions e publicar no
Entire somente o SHA aprovado, use Git e GitHub CLI (`gh`) autenticados:

```bash
python3 scripts/publish_with_ci.py
```

O comando exige uma branch diferente de `main` e diretório limpo. Ele publica
primeiro no remoto `github`, espera a CI daquele commit e verifica o sucesso dos
jobs `test`, `qdrant-legacy` e `import-macos`. Falha, cancelamento, jobs ausentes,
timeout ou mudança local durante a espera impedem a publicação no Entire. O
upstream fica no `origin`. A espera padrão é de 30 minutos; use `--timeout` para
ajustá-la em segundos.

Essa verificação é local: um `git push` direto ou `entire trail create` usado
isoladamente pode contorná-la. O bloqueio de merge no servidor depende de uma
integração de CI nativa, ainda pendente; veja [opções e estado](docs/ENTIRE_CI_OPTIONS.md).

Depois da publicação validada, abra um Trail explicando o problema, a solução,
o impacto e a validação, com o contexto do checkpoint e o link da execução de CI:

```bash
entire agent-help trail create
entire trail create --title "Atualizar fluxo de contribuição" \
  --body "Documenta o fluxo com Entire; incluir resultados da validação na revisão."
```

`trail create` também pode publicar a branch local; neste fluxo, execute-o depois
do publicador de CI e aguarde a revisão antes do merge.

**GitHub Actions:** um push apenas ao Entire não dispara os workflows em
`.github/workflows/`. Quando a revisão depender da CI existente no GitHub, envie
a mesma branch ao remoto `github` com `git push github HEAD` e abra um pull
request lá, vinculando-o ao Trail. O workflow roda em pushes para qualquer branch,
pull requests e disparos manuais. O publicador já envia a branch ao GitHub.
Esse comando preserva o upstream já configurado para o Entire.

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
