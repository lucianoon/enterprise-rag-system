# Piloto persistente de conhecimento interno

Este modo acrescenta interface em português, documentos duráveis, credenciais
individuais e autorização antes da recuperação. É um piloto de implantação
controlada em um servidor, não uma oferta SaaS validada comercialmente.
O motor experimental e seus benchmarks continuam disponíveis separadamente.

## Iniciar e provisionar

```sh
docker compose -f compose.product.yml up --build -d
docker compose -f compose.product.yml exec api python -m enterprise_rag_system.product_admin --database /app/state/registry.sqlite3 issue-user --tenant minha_empresa --user administrador --role admin
```

O segundo comando imprime uma credencial **uma única vez**. Guarde-a em um
gerenciador de senhas, abra `http://localhost:8000` e entre com ela. O navegador
mantém a credencial apenas na memória da página: recarregar exige nova entrada.
A saída do comando é sensível; não a inclua em logs, screenshots ou tickets.

Crie outras identidades repetindo `issue-user` com `--role editor` ou `reader`.
Repetir o mesmo tenant/usuário rotaciona a credencial e invalida a anterior.
Para revogar, use o mesmo prefixo de comando com
`revoke-user --tenant minha_empresa --user nome`. Não há cadastro público nem
expiração automática; o operador controla provisionamento e rotação.

O Compose publica somente em loopback, usa processo sem root e sistema de
arquivos somente leitura, exceto `/tmp` e o volume `product_state`. Acesso remoto
requer proxy com HTTPS e controle operacional do host. Este volume é novo e
independente dos volumes Qdrant existentes; não ocorre migração automática.
Não use `down -v` se pretende preservar os documentos.

Sem Docker: instale com `uv sync --extra dev --locked`, provisione com
`uv run python -m enterprise_rag_system.product_admin --database state/registry.sqlite3 ...`
e execute `RAG_PRODUCT_DB=state/registry.sqlite3 uv run uvicorn enterprise_rag_system.api:app`.
O diretório deve ficar em disco local persistente, acessível apenas ao operador.

## Permissões e documentos

| Papel | Permissões dentro do próprio tenant |
| --- | --- |
| reader | Consultar e abrir documentos autorizados |
| editor | Também criar, alterar permissões, editar e excluir documentos autorizados |
| admin | Todos os documentos do tenant, histórico, restauração e auditoria |

O tenant vem da credencial, nunca de um parâmetro fornecido pelo cliente.
Documentos começam privados. O proprietário mantém acesso; `readers` concede
acesso a usuários já provisionados no tenant, e `visibility=tenant` libera para
todos os usuários desse tenant. Editores autorizados podem alterar essas regras.
Administradores de um tenant não acessam outro tenant.

A biblioteca permite criar, editar, importar texto UTF-8 `.txt`/`.md`, excluir e,
para administradores, listar excluídos e restaurar conteúdo histórico. Não há
parser de PDF, OCR ou conectores externos. Cada gravação cria uma revisão;
`expected_revision` evita sobrescrever alterações concorrentes (HTTP 409).
A restauração cria uma nova revisão e conserva as permissões atuais.

Excluir retira o documento das consultas novas, mas **preserva o histórico**;
não é apagamento definitivo. Histórico e auditoria não têm expurgo automático.
Revogar uma credencial ou acesso vale para operações que começam depois da
transação confirmada; uma consulta em andamento pode terminar com o snapshot
anterior. Não há cache compartilhado de respostas ou contexto entre usuários.

## Respostas e limites

O modo padrão `RAG_PRODUCT_GENERATION=extractive` retorna trechos e fontes com
ID e revisão. Usa BM25 sobre os chunks dos documentos autorizados em cada
consulta. Não inicializa o corpus de demonstração nem Qdrant no startup.
`RAG_PRODUCT_DB` define esse modo; valor vazio é erro, não fallback para a demo.
As opções de recuperação do motor legado não alteram esse caminho.

A opção explícita `RAG_PRODUCT_GENERATION=llm` usa as configurações do cliente
LLM existentes e envia a pergunta e apenas os trechos autorizados ao provedor.
Marcadores inválidos ou falha do provedor resultam em trechos extrativos.
A validação de citações é **estrutural**, não prova de suporte factual ou defesa
completa contra prompt injection. `abstained` significa ausência de matches
BM25 positivos; não mede suficiência semântica da evidência.

Limites implementados: 200 documentos ativos por tenant; 32.000 caracteres por
texto; 64 MiB acumulados de texto em revisões por tenant; 128 KiB por requisição;
4.000 caracteres por pergunta; até 5 chunks por resposta; 30 consultas e
20 mutações por minuto por usuário, com contadores persistentes; 2 consultas
simultâneas por processo. HTTP 429/503 orienta repetição via `Retry-After`.
O limite de histórico não cobre o tamanho total do SQLite: metadados, auditoria
e documentos excluídos também ocupam disco. Monitore espaço e backups.
A capacidade para corpora maiores e múltiplos processos ainda exige teste de carga.

## Operação, backup e restauração

`/health` indica processo ativo; `/ready` verifica acesso ao registro.
`GET /quality?days=30` agrega consultas e avaliações do tenant (janela de 1 a
30 dias). O painel de acompanhamento apresenta participação, utilidade entre
avaliações, modos de resposta, motivos negativos e latências p50/p95.
`PUT /queries/{query_id}/feedback` aceita uma avaliação atual por consulta,
somente do próprio usuário; reenvios idênticos não duplicam nem consomem quota.
Alterações de avaliação compartilham o limite de 20 mutações/minuto.
`GET /audit` com Bearer de administrador retorna os 100 eventos mais recentes
do tenant (usuário, ação, recurso e horário), sem pergunta, texto ou token.
Consultas retornam revisão do corpus, modo de geração e latência total.
SQLite usa transações, WAL e esquema versionado; recusa downgrade de esquema
futuro e banco não relacionado. Não use filesystem de rede ou réplicas em hosts
diferentes compartilhando o mesmo arquivo.

Crie um backup consistente, incluindo dados ainda presentes no WAL:

```sh
docker compose -f compose.product.yml exec api python -m enterprise_rag_system.product_admin --database /app/state/registry.sqlite3 backup /app/state/backup-001.sqlite3
docker compose -f compose.product.yml cp api:/app/state/backup-001.sqlite3 ./backup-001.sqlite3
```

O destino deve ser novo; o comando não sobrescreve arquivos. Mova a cópia para
armazenamento protegido fora do host e teste restauração periodicamente. O
backup contém documentos e hashes das credenciais e deve ser tratado como
sensível. Copiar apenas o arquivo principal de um banco ativo pode perder WAL.

Para restaurar com reversibilidade, pare a API, preserve o volume original e
use **um novo volume/diretório** contendo o backup como `registry.sqlite3`.
Configure esse novo local como `/app/state`, garanta escrita pelo UID 1000,
inicie o serviço e confira `/ready`, documentos, revisões e consultas. Não
combine o backup com arquivos `-wal`/`-shm` antigos. Restaurar também restaura
credenciais, permissões e contadores daquele instante: rotacione/revogue chaves
que foram invalidadas depois do backup antes de reabrir o acesso.

## Evidência e próximos critérios

Testes cobrem isolamento entre tenants/usuários, revogação, concorrência,
restauração, limites, fallback e paridade do ranking com as 40 perguntas de
teste da baseline BM25 congelada. A CI exercita a imagem Docker com UI,
gravação, consulta, backup, restart e revogação. A interface foi verificada
interativamente em desktop e largura de 390 px.

Antes de oferta ampla: validar tarefas e qualidade com usuários e corpus real,
medir carga/latência/custo, definir retenção e apagamento definitivo, integrar
SSO e observabilidade operacional e testar recuperação de desastre no ambiente
escolhido. Esses itens não são declarados concluídos por este PR.

## Medição e atualização do registro

As consultas retornam `query_id`, gerado no servidor. O registro de medição não
contém pergunta, resposta, trecho, título ou ID de documento. Guarda identidade
para autorização, horário, revisão do corpus, modo de geração, contagem de
fontes e latência. Não é dado anônimo. A latência termina antes da gravação
dessa medição e da entrega HTTP; consultas rejeitadas ou interrompidas antes do
registro não entram no painel. Ausência de avaliações aparece como ausência
de medida, não 0% de qualidade. Veja [metodologia e fontes](QUALITY_MEASUREMENT.md).

Retenção: no máximo 10.000 consultas por tenant, dentro de 30 dias. Cada nova
consulta elimina medições antigas/excedentes daquele tenant. Para empresas
inativas, o operador deve executar periodicamente `prune-measurements` com o
mesmo prefixo CLI de backup. Consultas e feedback expirados ficam indisponíveis
mesmo antes dessa manutenção. O expurgo afeta somente medições, não documentos,
credenciais nem histórico. Não apaga backups ou garante limpeza física do disco.

O esquema passa de v1 para v2 automaticamente em transação, preservando os
registros existentes. Faça backup antes do upgrade. A versão anterior da
aplicação recusa abrir v2; rollback requer parar o serviço e restaurar o backup
anterior em volume separado, conforme o procedimento acima. Não altere
`user_version` manualmente. A aplicação revalida a credencial antes de registrar
e retornar a consulta: revogação durante a geração impede essa resposta, mas
mudança de ACL ainda respeita o snapshot lido no começo da consulta.
