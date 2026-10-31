# CI após a migração para Entire

Estado verificado em **31/10/2026**. O repositório é nativo: `/et/enterprise-rag-system/enterprise-rag-system`. Esta nota distingue execução de testes no GitHub de uma integração que efetivamente bloqueie merges no Entire.

## Estado atual

A consulta da API nesta sessão mostrou os gates `approvals`, `findings` e `up_to_date`, sem um gate de CI instalado. O catálogo consultado contém Buildkite e Depot, mas não havia conexão de provedor pronta nem organização Entire com credenciais de máquina configuradas.

O arquivo `.github/workflows/ci.yml` conserva os gates do projeto: lint, tipos, testes e cobertura, recuperação, Docker e testes específicos no macOS. Esses arquivos são configuração de **GitHub Actions**: ter uma cópia deles no Git do Entire não os executa. Actions precisa de um evento no repositório GitHub ou de outro disparo configurado. [GitHub: funcionamento de Actions](https://docs.github.com/en/actions/get-started/understand-github-actions).

**O caminho GitHub CI → publicação no Entire está implementado e validado.** O workflow roda em pushes de branches e pode ser iniciado manualmente. `python3 scripts/publish_with_ci.py` publica a branch no GitHub, exige sucesso do workflow no SHA exato e dos três jobs (`test`, `qdrant-legacy`, `import-macos`), e só então publica esse mesmo SHA no Entire. O commit `a12caa72f1ee` passou pelos três jobs e foi publicado em ambos os remotes.

Esse publicador é uma proteção local para quem o executa; um `git push origin` direto ainda pode contorná-lo. **O gate nativo de CI do Entire continua pendente.** Uma execução verde no GitHub, isoladamente, não comprova que um Trail do Entire recebe essa evidência ou bloqueia um merge quando ela falta.

## Caminhos documentados

| Caminho | Requisitos e resultado | Limite para este projeto |
| --- | --- | --- |
| Entire nativo + Buildkite | Conectar o projeto pelo plugin, selecionar o repo e criar um pipeline no Buildkite. Pushes podem criar builds e o provedor reporta um check global por pipeline/commit. [Buildkite: Entire](https://buildkite.com/docs/pipelines/source-control/entire). | Precisa de conta/conexão e executores. O fluxo de checkout automático documentado usa hosted Linux; preservar o teste macOS exige executor apropriado e configuração adicional. |
| Entire nativo + Depot | Instalar o plugin no projeto, escolher o repo e terminar o workflow no Depot. O Entire recebe suites e resultados por job. [Entire: conectar CI](https://docs.entire.com/guides/ci/connect-ci), [checks](https://docs.entire.com/guides/ci/checks). | Precisa de conta/conexão e verificar cobertura dos runners necessários. Copiar o YAML não demonstra equivalência dos ambientes. |
| GitHub como origem + mirror Entire | Pushes pelo mirror mantêm o fluxo do GitHub; Trails de mirrors podem exigir os checks vindos do GitHub. [CLI oficial](https://github.com/entireio/cli), [Entire: checks de mirrors](https://docs.entire.com/guides/ci/checks#github-mirrors). | É um modelo de hospedagem diferente do repositório nativo escolhido. A mudança não ocorre automaticamente e deve ser uma decisão explícita. |
| Executar CI no GitHub e publicar após aprovação | Preserva os runners e os testes existentes. O publicador local exige sucesso no SHA exato e dos três jobs antes de publicar no Entire. Validado em `a12caa72f1ee`. [GitHub Actions](https://docs.github.com/en/actions/get-started/understand-github-actions). | Não é um gate nativo do Entire e pode ser contornado por push direto. A documentação diz que o gate separado de checks GitHub está disponível apenas em mirrors. [Entire: checks](https://docs.entire.com/guides/ci/checks). |

As integrações Entire com Buildkite e Depot estão em **public preview**. Pipelines e comandos de build continuam no provedor de CI. [Entire: visão geral de CI](https://docs.entire.com/guides/ci/overview).

## O que falta validar para bloquear merges

Depois de conectar um provedor, configurar os checks requeridos com o **nome exato** reportado pelo plugin e verificar o resultado no commit atual do Trail. A documentação descreve uma exceção para commits anteriores à conexão, cujos resultados ausentes podem não bloquear. Também informa que um campo vazio de checks requeridos não exige necessariamente um build que nunca reportou resultado. Portanto, a prova deve usar um commit novo após a instalação. [Entire: requisitos e resultados](https://docs.entire.com/guides/ci/checks).

A validação completa precisa demonstrar três situações: falha real impede merge; ausência do resultado esperado impede merge; sucesso de todos os jobs, incluindo macOS, libera o commit correto. Um resultado verde de outro SHA não satisfaz essa prova.

A proteção `protected` do Entire impede force-push e exclusão, mas ainda permite push direto com fast-forward. A opção `--server-side-merge-only` impede todo push direto e exige merge feito pelo Entire; foi confirmada no help do CLI local `0.12.2`. Aplicar essa política exige primeiro preparar e validar o caminho de merge e seus checks, para não confundir bloqueio total com integração funcionando.

## Autenticação para automação

Não exportar o login pessoal de 30 dias para um secret de CI como solução permanente. O CLI aceita `ENTIRE_TOKEN`, mas isso descreve como consumir uma credencial, não como provisionar identidade de máquina de menor privilégio. [CLI oficial: automação](https://github.com/entireio/cli).

O OpenAPI de controle oferece service accounts: criação exige `orgId`; bindings OIDC usam um provedor e filtro de atributos; grants são por repo ou projeto com papel `reader`, `writer` ou `admin`. Não havia organização pronta nesta sessão. Provisionamento, confiança do issuer e autorização precisam ser resolvidos antes de declarar uma ponte OIDC funcionando. [Entire: contrato OpenAPI de controle](https://us.console.entire.io/api/v1/openapi.json).

No caminho Buildkite documentado, o job recebe uma credencial temporária de checkout com `contents:read`; a credencial `checks:write` usada para reportar o resultado fica separada, dentro do Buildkite. Não é necessário entregar ao job um login pessoal Entire. [Buildkite: credenciais de checkout e reporte](https://buildkite.com/docs/pipelines/source-control/entire).

## Deploy no Render

A associação do serviço Render ao repositório, à branch e ao commit esperado **ainda está pendente de verificação nesta etapa**. Mudar o `origin` local não muda automaticamente a configuração de deploy do serviço.
