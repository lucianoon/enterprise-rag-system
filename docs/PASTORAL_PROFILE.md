# Perfil pastoral: Pr. Luiz Hermínio

O perfil `luiz-herminio` carrega a instrução de sistema versionada em
`src/enterprise_rag_system/prompts/luiz-herminio.txt`. É um assistente de IA
inspirado em temas públicos, sem se apresentar como o pastor ou representante
oficial do MEVAM. [Pesquisa e fontes](PASTORAL_PROFILE_RESEARCH.md).

## Ativação

Configure no ambiente do processo da API:

```dotenv
RAG_PRODUCT_DB=state/registry.sqlite3
RAG_PRODUCT_PROFILE=luiz-herminio
RAG_PRODUCT_GENERATION=llm
```

Configure também o provedor através das opções existentes do cliente LLM
(`RAG_LLM_BACKEND`, `RAG_LLM_MODEL`, chave apropriada ou `RAG_LLM_BASE_URL`).
Não grave chaves no repositório. No Docker, essas configurações precisam estar
no ambiente do container, não apenas no shell do host. O Compose de produto
aceita perfil e modo de geração por interpolação; credenciais/provedor devem
ser fornecidos com um override local ou mecanismo de secrets do ambiente.

`GET /profile` expõe perfil, modo solicitado, identidade e hash SHA-256 do
prompt efetivo. Não é um teste de conectividade com o provedor. `/query` expõe
`editorial_profile`, `prompt_sha256` e o modo efetivamente usado na resposta.
Perfil desconhecido, arquivo ausente ou vazio causam erro de startup.

O perfil sozinho não ativa um modelo. No modo `extractive`, as respostas
continuam sendo trechos documentais. Em `llm`, falha do provedor ou citações
inválidas conserva o fallback extrativo, identificado em `generation_mode`.
A escolha do perfil pertence ao operador e não é aceita no corpo da consulta.

## Acervo e limites

Adicione documentos pastorais autorizados pela biblioteca ou pela API de
documentos. O prompt não importa livros ou sermões automaticamente. Sem fonte
recuperada, a consulta se abstém: este endpoint continua sendo um RAG documental,
não um chat pastoral irrestrito. Para atribuir uma ideia ao pastor, inclua na
fonte autoria e referência verificáveis. Não publique transcrições ou livros
integrais sem autorização adequada.

A filtragem de tenant e documento ocorre antes do contexto enviado ao modelo.
A checagem de citações continua estrutural; não comprova identidade correta,
fidelidade doutrinária ou ausência de alucinação. Testes de integração usam
provedor simulado para verificar o prompt efetivamente enviado e os contratos
negativos. Não representam uma avaliação do comportamento de um modelo real.

Para voltar ao comportamento geral, use `RAG_PRODUCT_PROFILE=default` e reinicie
a API. O perfil não altera o esquema do banco nem as permissões dos documentos.
