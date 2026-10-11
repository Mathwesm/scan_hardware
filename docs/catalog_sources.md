# Fontes e limites do catálogo de hardware

Avaliação iniciada em 07/10/2026; importação e auditoria atualizadas em 11/10/2026.
Escopo: placas-mães, placas de vídeo e processadores identificados pelo modelo ou
part number impresso.

## Fontes usadas pelo microserviço

| Fonte | Conteúdo útil | Uso atual e limite |
| --- | --- | --- |
| [Kaggle: PC Parts by Type](https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type) | 458 CPUs, 2.515 GPUs e 2.422 placas-mães; alguns códigos de produto, especificações e URLs de imagem. | Arquivo completo importado. A licença declarada CC0 para os dados não comprova direitos sobre fotos hospedadas por terceiros. |
| [Kaggle: PC Parts](https://www.kaggle.com/datasets/warcoder/pc-parts) | 1.341 linhas de CPU, 5.669 de placas de vídeo e 4.249 de placas-mães, com outras especificações. | Arquivo completo importado. Licença listada como desconhecida. Não traz fotos nessas três categorias. |
| Manuais da ECS para [A785GM-M3](https://www.scribd.com/document/442253904/A785GM-M3-manual) e [G41T-MR23](https://www.manualslib.com/manual/453017/Ecs-G41t-Mr23.html) | Identificadores e características de duas placas ausentes no Kaggle. | Dois itens suplementares, com sete especificações conferidas. São manuais do fabricante publicados em acervos externos; nenhum arquivo ou foto desses sites é redistribuído. |
| Páginas dos fabricantes | Valores específicos usados para resolver conflitos, como socket, TDP, VRAM e formato. | Onze valores conferidos no total, incluindo os sete valores das placas ECS. Cada evidência aparece na resposta da API. |
| Wikimedia Commons | Fotos de cinco produtos exatos com autoria e licença identificadas. | Referências externas com `image_attribution`. A licença deve ser exibida pelo consumidor. |

Os dois arquivos Kaggle completos estão em `data/raw/kaggle/` e são ignorados pelo
Git. O importador preserva todas as colunas originais em `source_records`, associa
linhas somente quando o produto é inequívoco e separa GPUs com chipsets distintos.
Uma URL de imagem entra apenas se parece ser uma foto de produto e não um placeholder.
Isso **não** confirma que ela funciona hoje ou que pode ser republicada.

## Estado da importação validada

| Categoria | Produtos distintos |
| --- | ---: |
| Processadores | 899 |
| Placas de vídeo | 7.549 |
| Placas-mães | 4.426 |
| **Total** | **12.874** |

Foram importadas 16.654 linhas relevantes dos dois arquivos Kaggle, sem rejeições
na execução auditada, mais dois itens suplementares. O importador preservou 4.655
URLs externas de imagem; cinco fotos de referência têm autoria e licença revisadas,
4.652 itens seguem sem revisão
de direitos e 8.217 produtos não têm imagem. A contagem de imagens revisadas pode
se sobrepor à contagem de URLs importadas, pois uma foto revisada substitui a URL
exibida de um item existente.

Os arquivos Kaggle não fornecem um ano de lançamento explícito para essas três
categorias. Há produtos antigos, mas a cobertura por década **não foi medida**.
Muitos identificadores entre parênteses precisam de conferência adicional para
serem considerados part numbers oficiais. `GET /items/{id}/sources` expõe as linhas
originais; `specifications` mostra valores normalizados, evidências e conflitos.

## Outras fontes avaliadas, ainda não importadas

| Fonte | Possível benefício | Decisão atual |
| --- | --- | --- |
| [Kaggle: GPU Specs Database 1995–2026](https://www.kaggle.com/datasets/riyagarg0314/gpu-specs-database-nvidia-and-amd-1995-2026) | 1.943 modelos de chip, datas e especificações históricas. | Útil para pesquisa, mas chip genérico não identifica necessariamente a placa de uma fabricante parceira. Não alimentar correspondência exata de SKU com ele. |
| [Open Icecat](https://icecat.com/content-subscription/) | Códigos de produto, GTIN, especificações, datas e referências de imagem. | Exigiria conta, auditoria de cobertura por categoria e cumprimento da [licença](https://iceclog.com/open-content-license/) e da [política de uso](https://iceclog.com/open-icecat-fair-use-policy/). Nenhum dado foi importado. |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access) | Dados estruturados CC0 e identificadores. | Pode ajudar a conferir lacunas; cobertura de SKUs e licenças de mídia devem ser avaliadas separadamente. |
| TechPowerUp | Referência histórica de GPU/CPU. | O [robots.txt](https://www.techpowerup.com/robots.txt) restringe mineração e coleta automatizada sem permissão escrita. Sem coleta. |
| [Dataset não oficial de PCPartPicker](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset) | Peças, especificações e links de imagem. | A licença declarada pelo uploader não estabelece direitos sobre dados e fotos da fonte original. Sem importação. |

## Critérios para uma futura ampliação

Antes de acrescentar uma fonte, medir quantidade de produtos por categoria, marca e
década; proporção com código identificável, especificações e imagem; duplicidades e
conflitos; e direitos de uso de dados e fotos. Guarde o registro bruto e sua origem,
rejeite linhas inválidas com motivo e publique uma nova versão do catálogo somente
depois dos controles de qualidade. Correspondências aproximadas continuam como
`suggestions`, nunca como identificação exata.
