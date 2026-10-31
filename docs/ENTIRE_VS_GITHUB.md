# Entire e GitHub: comparação para este repositório

Consulta às fontes oficiais em **31/10/2026**. Escopo: hospedagem Git, contexto de agentes, busca, revisão e CI para `enterprise-rag-system`. As capacidades descritas pelos fornecedores não constituem um resultado medido neste projeto.

## O que a migração já comprova

Na migração inicial, as **12 branches e a tag `v0.1.0`** foram comparadas por hash entre os destinos e coincidiram. O `origin` passou a apontar para um repositório Entire nativo no cluster `aws-sa-east-1.entire.io`, região Brasil; `github` preserva o remoto anterior. Isso comprova a cópia das referências e a configuração de hospedagem, sem demonstrar ganho de velocidade, disponibilidade ou produtividade.

No início do ensaio, o Entire local reportou integração Codex instalada, mas **6 hooks pendentes de aprovação**. Depois da aprovação e de uma nova sessão, a captura e o envio de um checkpoint foram verificados, conforme a validação posterior abaixo. A documentação recomenda iniciar uma nova sessão depois da instalação dos hooks e verificar a criação de um checkpoint ligado a um commit. [Entire: configuração e verificação de agentes](https://docs.entire.com/agents/setup).

## Capacidades documentadas e relevância prática

| Dimensão | Entire, segundo a documentação oficial | Comparação com GitHub e efeito neste projeto |
| --- | --- | --- |
| Hospedagem perto dos agentes | Repositórios nativos podem operar sem depender de GitHub, em clusters regionais; mirrors mantêm GitHub como origem. [Code Hosting](https://docs.entire.com/guides/repositories/overview). | A escolha Brasil já está configurada. GitHub também oferece residência regional por Enterprise Cloud, atualmente em EU, Austrália, EUA e Japão; isso é uma modalidade distinta do GitHub.com usado aqui. A doc informa armazenamento padrão do GitHub.com nos EUA. [GitHub: residência de dados](https://docs.github.com/en/enterprise-cloud@latest/admin/data-residency/about-github-enterprise-cloud-with-data-residency). Menor distância pode reduzir espera, mas depende da localização dos clientes e exige medição. |
| Rastrear decisões até o commit | Sessões guardam prompts, respostas, ferramentas e alterações; checkpoints ligam esse contexto ao commit por um trailer e armazenam metadados em refs Git próprias ou em uma branch de checkpoints. Podem incluir tokens e atribuição por linha. [Session Storage](https://docs.entire.com/guides/sessions/overview). | GitHub Copilot também tem histórico de sessões, logs de ferramentas, memória e continuidade entre clientes. A distinção do Entire é reunir contexto capturado de diferentes agentes e ligá-lo ao histórico Git pelo seu mecanismo de checkpoints. Neste repo, verificamos captura de uma sessão Codex e recuperação do pedido original por linha; facilidade de auditoria e produtividade ainda não foram comparadas entre produtos. [GitHub: Copilot e sessões](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github). |
| Alternar agentes | Integrações incluem Codex, Claude Code, Copilot CLI, Cursor, OpenCode e outras. Capacidades variam por agente; Codex, por exemplo, registra subagentes que alteram arquivos, mas não agrega seus tokens ao total do pai. [Matriz de integrações](https://docs.entire.com/agents/overview). | Potencial de preservar contexto quando o projeto troca de agente. Não há evidência local de redução de retrabalho. Não se deve supor captura idêntica para todos os agentes. |
| Buscar código e o motivo das mudanças | A busca combina código literal/símbolos com busca semântica em commits e sessões. [Agentic Search](https://docs.entire.com/guides/search/overview). Depende de sincronização e indexação; não vê alterações locais não commitadas, e nem todas as branches são pesquisadas. [Conteúdo indexado](https://docs.entire.com/guides/search/what-is-indexed). | GitHub Code Search oferece regex, operadores e símbolos na branch padrão; Copilot também oferece busca semântica e consulta ao histórico de sessões do próprio usuário quando sincronizado. [GitHub Code Search](https://docs.github.com/en/search-github/github-code-search/about-github-code-search), [Copilot](https://docs.github.com/en/copilot/concepts/copilot-surfaces/copilot-on-github). A melhoria a testar é encontrar decisões deste projeto com menos tempo e tokens, mantendo a qualidade. |
| Revisão ligada ao objetivo | Trails agrupam objetivo, mudanças de múltiplos repositórios, sessões e resultados. Gates podem exigir revisão humana, tratar findings de agentes e verificações. [Trails](https://entire.com/features/trails), [Gates](https://docs.entire.com/guides/trails/gates). | GitHub já permite reviews obrigatórios e status checks antes do merge; Copilot também revisa mudanças. A proposta do Entire organiza essas evidências em um Trail e permite conectar mudanças entre repos; isso não demonstra que seus reviews encontram mais bugs. [GitHub: branches protegidas](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches). |
| CI e integrações | CI via plugins Buildkite e Depot está em **public preview**. Os pipelines executam no provedor; Entire recebe resultados e pode exigi-los para merge. O gate separado de checks do GitHub se aplica a mirrors. [Entire CI](https://docs.entire.com/guides/ci/overview). | GitHub Actions executa workflows por push, PR, agendamento e outros eventos, com runners hospedados ou próprios. [GitHub Actions](https://docs.github.com/en/actions/get-started/understand-github-actions). A cópia de `.github/workflows/ci.yml` e `keepalive.yml` para Entire não instala um executor: pushes somente ao novo `origin` não chegam ao GitHub para disparar a CI existente. |
| Segurança de código | Os monitores e findings de Trails são sinais para revisão, cujo desempenho não foi aferido aqui. [Trails](https://entire.com/features/trails). | GitHub possui code scanning com CodeQL ou ferramentas SARIF, alertas e sugestões de correção; disponibilidade depende do tipo de repo/plano. Não há equivalência demonstrada entre esses mecanismos e scores de monitores do Entire. [GitHub: code scanning](https://docs.github.com/en/code-security/concepts/code-scanning/code-scanning). |

## O que significam os números anunciados

**“Até 89×” é uma alegação de throughput sob carga.** A página de Code Hosting mostra **418 pushes/s** para Entire e **4,7 pushes/s** para GitHub, atribuindo os resultados ao ForgeMark. Não é uma garantia de que um clone ou um push deste repositório levará 1/89 do tempo. [Entire: números publicados](https://entire.com/features/code-hosting).

O ForgeMark é um benchmark publicado pelo próprio Entire. Ele mede operações Git reais com clientes concorrentes, commits pequenos e diferentes estratégias. A metodologia ressalta influência da distância de rede e do gargalo do gerador. Também distingue repositório nativo de mirror: pushes por mirror fazem write-through ao GitHub e medem esse fluxo adicional. Um ensaio local sequencial de leitura não reproduz o cenário de throughput concorrente, e não confirma nem refuta o teto anunciado. [ForgeMark: método e limitações](https://github.com/entireio/forgemark).

**A busca tem um benchmark de fornecedor, não uma prova sobre este repo.** Entire informa **81/90 respostas corretas**, contra **70/90** usando o mesmo agente com histórico Git completo e GitHub CLI, em nove perguntas da sua própria engenharia repetidas dez vezes. O corpus é interno ao fornecedor; o comparador é o fluxo Git+`gh`, não toda a oferta atual de Copilot. Esses números justificam um teste próprio de recuperação de decisões, sem prometer o mesmo ganho aqui. [Entire: benchmark de busca e harness](https://docs.entire.com/guides/search/overview).

## Medições neste repositório

Ensaio em **31/10/2026, 13:01:53–13:02:13 UTC**. Os dois destinos tinham as mesmas 12 branches, uma tag e **89 commits alcançáveis**. Os packs dos clones ficaram próximos de 692 kB. Ambiente: macOS 27.0.1 arm64, Git 2.54.0, Python 3.14.8 e Entire CLI 0.12.2. O destino Entire foi o cluster Brasil; não medimos nem controlamos a localização física do cliente ou a rota de rede.

| Operação | Repetições por serviço | GitHub, mediana | Entire, mediana | Redução do tempo no Entire |
| --- | ---: | ---: | ---: | ---: |
| Listar branches e tags (`ls-remote`) | 7 | 567,1 ms | 298,0 ms | **47,5%** |
| Clone completo bare, sem checkout | 3 | 971,4 ms | 570,9 ms | **41,2%** |
| Fetch sem mudanças | 5 | 573,9 ms | 332,3 ms | **42,1%** |

Faixas observadas, mínimo–máximo: listagem GitHub 528,1–592,5 ms e Entire 272,9–347,0 ms; clone GitHub 935,7–988,2 ms e Entire 531,8–839,0 ms; fetch GitHub 546,5–588,4 ms e Entire 281,5–551,2 ms. O Entire teve menor mediana nas três operações, com maior variação nos clones e fetches. As economias absolutas medianas foram aproximadamente **269 ms, 400 ms e 242 ms**, respectivamente.

Método: uma rodada de aquecimento descartada por operação e serviço; ordem dos serviços alternada a cada rodada; clones em diretórios temporários novos; tempo total do processo, incluindo transporte, rede e autenticação. GitHub usou o remoto HTTPS e Entire seu helper `entire://`: medimos o fluxo disponível ao usuário, sem isolar o servidor da diferença de protocolos. Não houve flush de caches do cliente ou servidor. Todas as operações concluíram, e as referências coincidiram antes e depois. Os refs de cada clone também foram comparados aos de origem.

**Conclusão restrita ao ensaio:** neste repositório pequeno e nesta janela, as leituras pelo Entire consumiram de 41% a 48% menos tempo mediano. A amostra não estima disponibilidade, custo, latência sob outras conexões, checkout, push com alterações ou throughput concorrente. Três clones não sustentam uma previsão de percentis extremos ou uma promessa geral de desempenho. O ganho observado não pode ser atribuído isoladamente à região Brasil.

Artefatos: [dados brutos e ambiente](results/entire-vs-github-2026-10-31.json), [script de reprodução](../scripts/benchmark_git_hosts.py). O script não altera refs remotos; usa clones temporários e exige que branches e tags sejam idênticas. Para repetir em uma nova janela, mantendo o relatório original:

```bash
python3 scripts/benchmark_git_hosts.py \
  --github-remote github --entire-remote origin \
  --refs-runs 7 --clone-runs 3 --fetch-runs 5 \
  --output /tmp/entire-vs-github-repeticao.json
```

O snapshot medido tinha `main` em `86a279bef4f508d3a256c7e685b90a7848836614`. Os commits posteriores publicados somente no Entire fazem os destinos divergir; nessa condição, o script interrompe antes das medições. Para repetir a comparação, use destinos com as mesmas branches e tags. Os dados históricos acima permanecem referentes ao snapshot original.

### Funcionalidades verificadas no início do ensaio

- `entire checkpoint list --json` e `entire session list --json` retornaram arrays vazios; `entire status` apontou seis hooks Codex pendentes. **Não foi medido ganho de produtividade, economia de tokens ou recuperação de decisões de sessões.**
- `entire search --code BM25 --limit 3 --json` retornou três resultados; as estatísticas do serviço informaram **204 ocorrências em 42 arquivos**, um repo e 10 ms de processamento interno. Isso confirma disponibilidade da busca de código, sem medir qualidade semântica, tempo total de ponta a ponta ou vantagem sobre a busca do GitHub. A consulta foi de código, não de sessões.
- Os workflows [CI](../.github/workflows/ci.yml) e [keepalive](../.github/workflows/keepalive.yml) continuam escritos para GitHub Actions. O primeiro tem gatilhos de push em `main` e pull request; um push só ao Entire não produz esses eventos no GitHub. O agendamento do keepalive permanece vinculado ao repositório GitHub. Não foi configurado um pipeline Entire equivalente durante a migração.

### Validação posterior dos hooks e da sincronização

Ainda em 31/10/2026, os seis hooks foram aprovados no gerenciador `/hooks` do Codex. Uma nova sessão executou a atualização do guia de contribuição e criou o commit `7ba87cb531845f8a46ca4a5e01a3de43f1209c42`, com o trailer `Entire-Checkpoint: 01M691E08MFQSDZDS49A9M6T0W`.

Verificações realizadas:

- `entire status --json` deixou de indicar aprovações pendentes.
- `entire session list --json` mostrou a sessão Codex `01a19215-a994-79f1-af79-b5674061fce0`.
- `entire checkpoint explain --commit HEAD --json`, executado naquele commit, vinculou o checkpoint à sessão e ao arquivo `CONTRIBUTING.md`; o transcript completo armazenado tinha 110 linhas JSONL.
- `entire why CONTRIBUTING.md:13 --json` recuperou a linha, o pedido original, o commit, o checkpoint e a sessão.
- `git push origin main` enviou o commit e o checkpoint automaticamente pelo hook pre-push. `git ls-remote` confirmou o commit em `refs/heads/main` e o checkpoint em `refs/entire/checkpoints/0W/01M691E08MFQSDZDS49A9M6T0W`, com os mesmos hashes locais. A fila de `entire checkpoint list --outgoing --json` ficou vazia.

Isso comprova captura, vínculo por linha e sincronização de uma sessão real. Não mede redução de retrabalho, bugs, custo ou tokens em relação ao GitHub. As configurações compartilhadas não substituem a instalação de hooks Git e a aprovação local em cada clone; veja [CONTRIBUTING.md](../CONTRIBUTING.md).

O benefício de desempenho medido é menos espera em leituras Git; a rastreabilidade também passou a ter uma demonstração funcional neste projeto. A continuidade dos gates da CI precisa ser resolvida para que o novo remoto seja também o centro do fluxo de entrega.

## Como avaliar o ganho real de uso

| Resultado desejado | Medida adequada | Limite de interpretação |
| --- | --- | --- |
| Menos espera no Git | Mediana e dispersão de `ls-remote`, clone e fetch sob as mesmas opções, máquina e conteúdo; registrar erros. | Operação sequencial pequena não mede teto de escala de agentes. |
| Melhor rastreabilidade | Proporção de commits de agente com checkpoint válido e transcript acessível; registrar os hooks ativos. | Configuração instalada e quantidade de checkpoints não medem qualidade. |
| Recuperar decisões mais rápido | Mesmo conjunto de perguntas reais, respostas corretas verificadas por evidência, tempo, tokens e passos, comparando fluxos definidos. | Sem perguntas equivalentes e critério de acerto, comparação de produtividade fica subjetiva. |
| Revisar com mais qualidade | Defeitos confirmados encontrados, falsos positivos e tempo de revisão em mudanças equivalentes. | Scores de risco de ferramentas diferentes não têm escala necessariamente comparável. |
| Manter os gates do projeto | Executar lint, tipos, testes, cobertura, benchmarks de recuperação e smoke Docker no provedor escolhido. | Hospedar o Git no Entire não migra automaticamente pipelines, configurações de PRs, issues ou proteções. |

A escolha regional e a hospedagem independente do GitHub já são mudanças concretas de configuração. Captura de sessão, recuperação do pedido por linha e envio do checkpoint foram demonstrados; ganho de produtividade, revisão e uso de Trails ainda exigem medição. Para este projeto, preservar a CI existente ou conectar um provedor equivalente é parte necessária de uma migração operacional completa.
