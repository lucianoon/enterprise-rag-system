# Documentos grandes

O formulário principal agora usa `POST /uploads?filename=...` com o corpo binário
do arquivo. O servidor grava em disco conforme recebe os blocos, sem base64 e sem
carregar o upload inteiro na memória. Não há teto configurado de tamanho de arquivo,
número de páginas ou caracteres nesse fluxo. O antigo teto de 64 MB para histórico
do tenant também foi removido.

O servidor retorna 202 e um job_id. Extração e embeddings continuam em segundo
plano. A tela acompanha `queued → extracting → indexing → ready`; somente depois
seleciona o documento para perguntas. As chamadas de embeddings continuam em lotes,
e os pontos no Qdrant são gravados e verificados em lotes.

Originais ficam no volume persistente, em `state/uploads`, com nomes internos e
permissão 0600. O texto integral é salvo no SQLite. Conteúdo não é truncado.
Jobs e seus estados são persistidos; não são armazenadas chaves nem tokens neles.
Depois de reiniciar o serviço, trabalhos interrompidos ficam disponíveis para
retomada explícita após autenticação. O mesmo job_id evita duplicar o documento
caso o serviço tenha parado entre o salvamento e a confirmação.

## Limites de recursos que continuam existindo

"Sem teto de documento" não significa recursos infinitos:
- Uploads preservam 64 MB livres no disco e falham com 507 se faltar espaço.
- Um trabalhador executa indexações, com até quatro trabalhos aceitos na fila.
- O parser tem orçamento de memória de 768 MB, ajustável por
  `RAG_IMPORT_MEMORY_MB`. O processo principal ainda materializa texto/chunks,
  portanto RAM e armazenamento disponíveis delimitam o tamanho viável.
- Cada chamada externa de OCR tem timeout, mas não existe o antigo timeout total
  de 90 segundos. PDFs protegidos ou danificados continuam sendo rejeitados.
- Limites e custos dos provedores de embeddings continuam aplicáveis.
- A configuração atual pressupõe uma única instância da API. Para múltiplos
  workers/réplicas, migrar coordenação para uma fila distribuída com leases.
- As rotas JSON legadas de importação continuam limitadas; arquivos grandes devem
  usar `/uploads`. Edições manuais JSON não são o caminho para substituir arquivos grandes.

A aplicação não faz purga automática de originais ou histórico. Dimensione o volume
persistente e sua política de retenção. Não execute containers antigo e novo sobre
o mesmo banco simultaneamente durante jobs.
