# Importação de documentos

**Fluxo atual:** o formulário principal usa upload em streaming e indexação em
segundo plano, sem os tetos de 5 MB, 20 páginas e 32 mil caracteres. Veja
[LARGE_DOCUMENTS.md](LARGE_DOCUMENTS.md). Os limites abaixo se aplicam apenas
às rotas JSON legadas.

Na biblioteca, escolha **Novo documento → Importar TXT, MD, PDF ou DOCX**.
A extração preenche o editor; revise o conteúdo, defina o identificador e as
permissões e clique em salvar. Importar sozinho não grava no acervo.

- TXT e Markdown: UTF-8.
- DOCX: parágrafos e texto de tabelas do corpo principal. Imagens, notas,
  cabeçalhos e rodapés não são importados.
- PDF: texto por página; páginas com menos de 30 caracteres passam por OCR
  Tesseract em português e inglês. PDFs mistos podem exigir revisão: imagens
  em páginas que já contêm texto suficiente não passam por OCR.
- Limites: 5 MB por arquivo, 20 páginas por PDF, 32 mil caracteres extraídos,
  90 segundos de processamento e duas extrações simultâneas por processo.
  Arquivos que excedem limites são rejeitados sem truncamento silencioso.
- PDFs protegidos devem ser desbloqueados antes de importar.
- OCR pode errar: sempre revise nomes, números e referências bíblicas.

A imagem Docker instala Poppler e Tesseract com idiomas `por` e `eng`.
A execução fora do Docker exige esses executáveis no PATH e ambiente Unix
com suporte a `resource`. Extração ocorre em processo separado com limites
de memória, CPU e arquivo; arquivos temporários são removidos ao concluir.
As credenciais do provedor não são transmitidas ao processo de extração.

API: `POST /imports/extract`, com Bearer token de editor/admin e JSON
`{"filename":"arquivo.pdf","content":"<base64>"}`. Retorna `text` e
`ocr_pages` (páginas numeradas a partir de 1). Não altera documentos;
use o endpoint existente `PUT /documents/{doc_id}` após revisão.

## Fluxo direto: indexar e perguntar

Use o formulário **1. Escolha seu documento → 2. Indexar documento** na biblioteca.
O arquivo é extraído, recebe embeddings e seu texto é salvo como um novo documento
privado. Não é preciso preencher um identificador nem clicar em salvar novamente.
O aviso de conclusão informa quantos caracteres e trechos foram indexados.
O original binário não é arquivado: o acervo persiste seu texto extraído e vetores.

A seleção **3. Perguntar sobre** limita a recuperação ao documento escolhido,
inclusive para leitores; documentos sem acesso retornam 404. Depois de indexar,
o novo documento é selecionado automaticamente. Também é possível escolher todos.

`POST /imports/index` recebe `filename`, `content` (base64) e `doc_id` único.
Exige editor/admin e busca híbrida habilitada. Se a extração ou a geração de
embeddings falhar, não cria um documento incompleto. IDs existentes retornam 409,
sem sobrescrever conteúdo. O fluxo manual anterior permanece no editor avançado.
`POST /query` agora aceita `doc_id` opcional para restringir as fontes.
