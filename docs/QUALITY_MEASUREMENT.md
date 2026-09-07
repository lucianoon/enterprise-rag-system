# Medir utilidade e operação sem guardar conversas

Pesquisa consultada em 7 de setembro de 2026. Este documento registra a decisão
de medição do piloto; não apresenta resultados de usuários nem comprova liderança
de mercado.

## Evidência que orienta a mudança

A Microsoft separa a avaliação da recuperação da avaliação da resposta. Relevância,
suporte no contexto e completude respondem a perguntas diferentes; a mera presença
de uma citação não comprova que a afirmação esteja correta.
[Microsoft: avaliadores RAG](https://learn.microsoft.com/en-us/azure/foundry/concepts/evaluation-evaluators/rag-evaluators).

O relato de engenharia do Ask Learn recomenda um conjunto de perguntas, respostas
aprovadas e fontes, revisado por especialistas, para comparar mudanças antes e
depois. O feedback do uso complementa esse conjunto, mas não o substitui.
[Microsoft: construção do Ask Learn](https://devblogs.microsoft.com/engineering-at-microsoft/how-we-built-ask-learn-the-rag-based-knowledge-service/).

As convenções GenAI do OpenTelemetry consideram instruções, entradas e saídas
conteúdo sensível e recomendam não capturá-las por padrão. A documentação está em
desenvolvimento e foi movida para um repositório próprio. Usamos essa orientação
de minimização; o registro local descrito abaixo não constitui uma implementação
do protocolo OpenTelemetry.
[OpenTelemetry: captura de conteúdo](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-spans.md#capturing-instructions-inputs-and-outputs).

## Decisão de aplicação

Cada consulta concluída recebe um identificador opaco gerado pelo servidor,
vinculado à empresa e ao usuário autenticado. Ele permite avaliar somente a
própria consulta, sem aceitar identidade enviada pelo cliente. Esse identificador
é de consulta da aplicação, não um `gen_ai.conversation.id` inventado.

O registro guarda horário, latência, revisão do corpus, modo de geração, indicação
de abstenção e quantidade de citações. Não guarda pergunta, resposta, trechos,
títulos, IDs de documentos nem credenciais. Os campos de identidade necessários
à autorização continuam sendo dados de acesso restrito; o registro não é anônimo.

O usuário pode marcar `helpful` ou `not_helpful`, com motivo de uma enumeração
fechada. Não há comentário livre. Uma avaliação atual por consulta evita contar
cliques repetidos como opiniões independentes. Uma marcação negativa é relato de
experiência; não é uma constatação automática de erro factual.

Os agregados são restritos ao administrador da própria empresa. A janela é de
30 dias e contém no máximo as 10.000 consultas mais recentes por empresa. Esses
limites são escolhas do produto para conter armazenamento e custo de consulta;
não são requisitos da Microsoft, do OpenTelemetry ou uma certificação de
conformidade. O teto pode encurtar o período efetivamente representado. Expurgo
lógico também não apaga automaticamente cópias em backups ou páginas livres do
SQLite; a política operacional dessas cópias deve acompanhar a retenção.

## Denominadores e interpretação

Considere `Q` as consultas concluídas e retidas na janela, `F` aquelas com feedback
e `H` aquelas marcadas úteis. O painel deve apresentar os totais junto às taxas:

| Medida | Cálculo e limite |
| --- | --- |
| Participação no feedback | `F / Q`; ausência de avaliação não significa satisfação |
| Utilidade entre avaliações | `H / F`; não é precisão factual nem satisfação de todos os usuários |
| Abstenção | Consultas sem evidência recuperada divididas por `Q`; exige revisão separada de falsos negativos |
| Modo de resposta | Contagem por modo, incluindo fallback; misturar modos pode esconder regressões |
| Latência | Distribuição das consultas concluídas retidas, com tamanho da amostra; não mede indisponibilidade |

Denominador zero produz ausência de medida, não 0% de qualidade. Consultas
rejeitadas, interrompidas ou com falha antes do registro não pertencem a `Q`;
disponibilidade e taxa de erros exigem métricas HTTP operacionais separadas.
Uma janela limitada não representa o histórico completo de uso.

Como inferência metodológica para este piloto, avaliações espontâneas podem
super-representar experiências muito boas ou ruins. Exibir a participação torna
esse viés visível, mas não o corrige. Comparar também sessões de tarefas
predefinidas com usuários convidados, incluindo quem normalmente não avalia,
ajuda a investigar a diferença. Metadados sem texto não permitem reconstruir
uma resposta problemática; estudos de conteúdo devem usar exemplos autorizados
e um fluxo separado, com acesso e retenção definidos.

## Critérios propostos para o piloto

Antes da coleta, acordar domínio, tarefas, usuários, duração e limiares de aceite.
Não escolher um limiar depois de observar a melhor configuração.

- Comparar tempo e conclusão correta de tarefas com a busca atual, usando o mesmo
  corpus e uma distribuição equilibrada da ordem das ferramentas.
- Anotar uma amostra autorizada com especialistas: relevância, suporte de cada
  afirmação, completude e abstenções corretas/incorretas. Relatar divergências
  entre avaliadores e quantidade de exemplos.
- Preservar o conjunto de teste congelado e publicar regressões por pergunta;
  separar resultados sintéticos de tarefas reais.
- Relatar feedback com seus denominadores e janela efetiva, sem inferir resultado
  de quem não respondeu. Poucas avaliações são evidência insuficiente.
- Medir latência sob carga com hardware, tamanho do corpus e concorrência
  declarados; validar isolamento, revogação, retenção e restauração por testes.

Revisitar a avaliação quando o corpus e as perguntas mudarem segue a orientação
de avaliação contínua da Microsoft. Nenhuma das medições propostas acima foi
executada com clientes reais por este documento.
[Microsoft: avaliação de ponta a ponta](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/rag/rag-llm-evaluation-phase).
