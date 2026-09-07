# Estratégia de ingestão segura para o piloto

Pesquisa e decisão: 7 de setembro de 2026.

## Objetivo do produto

Começar com uma instalação dedicada para uma empresa e um operador responsável
pelos documentos. Antes de abrir um SaaS com várias empresas, precisamos de
identidades, autorização na recuperação e um ciclo de vida de documentos
persistente. A prioridade desta entrega é impedir perda de índices existentes
quando um processo inicia ou uma nova indexação falha.

## Pesquisa e alternativas

A [documentação da Qdrant](https://qdrant.tech/documentation/manage-data/collections/)
explica gerações em coleções separadas e troca atômica de aliases. Também ressalta
o custo de muitas coleções. A [orientação OWASP para RAG](https://cheatsheetseries.owasp.org/cheatsheets/RAG_Security_Cheat_Sheet.html)
trata ingestão e recuperação como fronteiras de segurança, com verificação de
permissões dos documentos durante a consulta. Usamos essas orientações como
base; elas não certificam esta implementação.

| Estratégia | Benefício | Risco neste código | Decisão |
|---|---|---|---|
| Apagar/recriar coleção | Simplicidade | Uma falha elimina o índice anterior; workers sobrescrevem dados | Removida |
| Upsert na mesma coleção | Evita recriação | Escrita parcial, chunks antigos remanescentes, mistura de versões | Adiar até existir registro transacional de documentos |
| Trocar alias compartilhado | Publicação atômica do vetor | Texto e índice lexical continuam locais; leitores antigos podem combinar versões diferentes | Adiar até versionar o corpus inteiro |
| Coleção imutável por geração e leitor vinculado | Preserva índices e mantém cada adaptador na sua versão | Consome armazenamento por inicialização; precisa de retenção operacional | Implementada para o piloto |

A escolha é uma inferência da arquitetura atual: o retriever mantém textos,
IDs e índice lexical em memória. Trocar apenas um alias remoto não atualizaria
esses componentes de forma atômica. Por isso cada instância do adaptador fica
vinculada ao nome físico que ela construiu, sem um alias global mutável.

## Contrato implementado

1. Copiar e validar IDs, quantidade, dimensão e valores finitos de todos os vetores.
2. Criar uma coleção nova com nome `<namespace>__generation_<uuid>`.
3. Gravar lotes de até 256 pontos com `wait=True`, exigindo status `completed`.
4. Conferir a quantidade exata de pontos antes de disponibilizar a geração.
5. Atualizar a referência local somente após todas essas verificações.

Leituras em curso capturam uma referência ao nome físico. Enquanto a geração
nova está sendo construída, consultas continuam usando a anterior. Instâncias
diferentes com o mesmo namespace criam coleções diferentes. Trocas de dimensão
são possíveis porque cada geração tem sua configuração própria.

Falhas de criação, upload, confirmação ou contagem não alteram a referência
anterior. Não há deleção automática — nem depois de timeout, cujo resultado
remoto pode ser incerto. O nome da geração é registrado em log antes da criação.
`active_collection` permite ao operador consultar a geração ativa da instância.

`index([], [])` esvazia a visão daquela instância, sem apagar coleções retidas.
O backend em memória também valida a entrada inteira antes de substituir sua
visão. O protocolo continua representando uma substituição completa, não uma
inserção incremental de documentos.

## Carregar documentos próprios

O arquivo é definido pelo operador, não por um parâmetro público HTTP:

```bash
RAG_DOCUMENTS_PATH=/caminho/corpus.jsonl \
RAG_RETRIEVAL_MODE=bm25 \
RAG_VECTOR_STORE=memory \
RAG_LLM_MODE=deterministic \
uv run uvicorn enterprise_rag_system.api:app --host 127.0.0.1
```

Cada linha JSON contém `doc_id`, `title` e `text`. Os três campos precisam ter
conteúdo, os IDs devem ser únicos e o corpus não pode estar vazio. Se a variável
não estiver definida, os documentos de demonstração continuam sendo usados.
Um caminho explicitamente inválido causa falha na inicialização; não há fallback
silencioso para o exemplo. Arquivos relativos são resolvidos pelo diretório de
trabalho do processo. Reinicie a API para carregar uma nova versão do arquivo.

No Docker, monte o diretório de documentos como somente leitura e indique o
caminho interno em `RAG_DOCUMENTS_PATH`. O modo determinístico é uma demonstração
de recuperação; não substitui validação de respostas geradas por um LLM.

## Operação e limites que permanecem

- `COLLECTION_NAME` agora é um **prefixo**, não o nome de uma coleção ativa
  compartilhada. Coleções legadas existentes permanecem intactas e não são
  importadas automaticamente. A API sempre reconstrói a partir do JSONL configurado.
- Cada inicialização não vazia cria outra coleção, inclusive quando o corpus
  não mudou. Use inicialmente uma instância por instalação e acompanhe espaço
  em disco. Esta entrega não resolve ingestão incremental nem reutilização no restart.
- Gerações antigas ou incompletas ficam retidas. Um operador precisa inventariar
  leitores ativos e drenar processos antes de remover coleções. Não apague por
  idade apenas: um processo antigo pode continuar lendo sua geração.
- Não há limpeza automática, registro durável de gerações, rollback administrativo
  ou política de retenção ainda. Sem esses controles, não promover para operação
  prolongada ou escala com muitos workers.
- O termo geração não significa um arquivo de backup Qdrant. Preserve o JSONL
  original e backups do armazenamento. Os payloads vetoriais contêm somente o
  ID do chunk; eles não permitem reconstruir o texto original.
- Construa um adaptador novo por pipeline. Reindexar um adaptador compartilhado
  entre retrievers não atualiza seus textos/índices lexicais. Esta entrega não
  adiciona hot reload da pipeline nem API pública de ingestão.
- A coleção nova é imutável pelo código da aplicação; um administrador Qdrant
  ainda pode modificá-la. A contagem verifica completude da gravação, não é uma
  auditoria criptográfica nem uma garantia contra administradores maliciosos.
- Nenhuma separação por namespace aqui representa autenticação ou autorização.
  A chave global opcional e a ausência de permissões por documento permanecem.
  O banco precisa ficar em rede privada. Não exponha dados de várias empresas
  nesta versão como se já houvesse isolamento de clientes.

## Verificação

Testes locais injetam falha no segundo lote, status não concluído, recusa de
criação e contagem divergente. Os testes verificam que a geração anterior
continua consultável. Testes de contrato executam tanto no cliente local quanto
em um Qdrant descartável real na CI: preservação da coleção legada, instâncias
com o mesmo namespace, mudança de dimensão e leitor durante construção.

A CI usa `qdrant/qdrant:v1.12.4`, mesma versão já declarada no Compose, e um
namespace UUID exclusivo por teste. A limpeza dos testes é restrita a esses
namespaces. Para executar os contratos remotos, forneça `RAG_QDRANT_TEST_URL`
apontando para um servidor de teste descartável. Não use o banco de produção.

As três referências de recuperação anteriores permanecem congeladas. Este
trabalho não modifica o ranking e deve passar pelos mesmos controles de qualidade.

## Próximas decisões, em ordem

1. Registro durável de documentos e gerações, com hash do corpus/modelo/analisador,
   estado de publicação e vínculo dos leitores. Isso permite reutilização,
   retenção e recuperação verificável sem inferir segurança só pela idade.
2. Separar ingestão da inicialização HTTP: job validado publica o corpus completo;
   leitores abrem uma versão pronta, sem escrever no banco ao iniciar.
3. Identidades e autorização na busca lexical e vetorial, com testes negativos
   de revogação e isolamento. Avaliar se o piloto dedicado atende o mercado antes
   de adotar uma arquitetura compartilhada de múltiplas empresas.
4. Validar citações, abstenção, qualidade e custo com um corpus autorizado e
   anotação humana. Depois disponibilizar a interface de documentos e perguntas
   ao usuário piloto, com limites de consumo e observabilidade.
