# Corporate PT v1 — conjunto sintético de regressão

Este conjunto foi escrito com assistência de IA para este repositório. Os
documentos descrevem uma empresa **fictícia**, Aurora. Valores, prazos,
benefícios e processos foram inventados. Não são políticas reais, orientação
jurídica ou recomendações de segurança para uma organização.

## Conteúdo e propósito

- 30 documentos: viagens, financeiro, pessoas, acessos, privacidade, operações e software.
- 80 perguntas: 40 de desenvolvimento (`dev`) e 40 de teste (`test`).
- Cada split contém 30 perguntas com uma fonte, 5 com duas fontes e 5 sem resposta.
- Há paráfrases, exceções, documentos parecidos e questões que exigem combinar fontes.
- Rótulos binários em nível de documento; IDs vazios indicam ausência de resposta no corpus.

O conjunto substitui a avaliação apenas com três documentos como **instrumento
de diagnóstico**. Ele não substitui avaliação independente com dados reais nem
constitui um benchmark público de liderança de mercado.

Os documentos são compartilhados entre os splits, como num índice consultado
por diferentes perguntas. Perguntas idênticas, inclusive após normalizar caixa
e espaços, são rejeitadas pelo carregador. O teste contém mais paráfrases e não
foi obtido por amostragem aleatória. Os rótulos foram revisados durante a
autoria, mas **não receberam anotação humana independente**.

## Uso dos splits

Use `dev` para examinar erros, calibrar configurações e formular hipóteses.
Congele dados e hipóteses antes de medir `test`. Não ajuste pesos ou limiares
para recuperar uma nota específica no teste. A execução recorrente em CI torna
esse teste um conjunto de regressão conhecido; uma alegação de generalização
exige outro conjunto de teste, independente e ainda não usado no desenvolvimento.

Nesta versão inicial, o algoritmo de busca padrão não foi ajustado aos novos
rótulos. As ablações apenas desligam componentes existentes para medir sua
contribuição. A baseline fixa registra o comportamento atual, incluindo erros.

## Casos sem resposta

`relevant_doc_ids: []` significa que o corpus não contém a informação pedida.
Exemplos incluem uma senha atual, um valor salarial, a duração de um benefício
não especificada e um prazo que a política declara não ser fixo.

Essas perguntas ficam fora das médias de Recall, MRR, nDCG e precisão. O relatório
mostra separadamente a proporção que recebeu algum resultado de busca
(`unanswerable_return_rate`). O retriever atual sempre retorna candidatos para
um corpus não vazio, portanto a taxa inicial é 1,0. Isso **não mede alucinação**:
um gerador ainda pode reconhecer a falta de evidência e se abster de responder.

## Alterações e licença

As linhas JSONL são os dados de referência, sem downloads externos ou chaves.
O relatório registra SHA-256 dos dois arquivos completos. Qualquer mudança nos
dados invalida a comparação automática com a baseline antiga e deve passar por
revisão explícita de documentos, perguntas e rótulos. Não atualize a baseline
apenas para esconder uma regressão de código.

O conteúdo original deste diretório segue a licença MIT do repositório.
