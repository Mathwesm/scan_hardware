# Fontes e limites do catálogo de hardware

Avaliação iniciada em 07/10/2026; imagens e auditoria atualizadas em 12/10/2026.
Escopo: placas-mães, placas de vídeo, processadores, memórias RAM, fontes, gabinetes,
coolers de CPU e armazenamento identificados pelo modelo ou
part number impresso.

## Fontes usadas pelo microserviço

| Fonte | Conteúdo útil | Uso atual e limite |
| --- | --- | --- |
| [Kaggle: PC Parts by Type](https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type) | CPUs, GPUs, placas-mães, 1.707 linhas de RAM, 2.314 fontes, 1.571 gabinetes, 872 coolers e 2.172 unidades de armazenamento; códigos, especificações e URLs de imagem. | As oito categorias são importadas. A licença declarada CC0 para os dados não comprova direitos sobre fotos hospedadas por terceiros. |
| [Kaggle: PC Parts](https://www.kaggle.com/datasets/warcoder/pc-parts) | 1.341 linhas de CPU, 5.669 de placas de vídeo, 4.249 de placas-mães e 11.323 linhas de memória, além de fontes, gabinetes, coolers e discos sem código de peça. | CPU, GPU e placa-mãe são importadas. As outras categorias só usam o CSV com part number para identificação exata; as 9.205 linhas de RAM com nome repetido não distinguem kits. Licença listada como desconhecida. |
| Manuais da ECS para [A785GM-M3](https://www.scribd.com/document/442253904/A785GM-M3-manual) e [G41T-MR23](https://www.manualslib.com/manual/453017/Ecs-G41t-Mr23.html) | Identificadores e características de duas placas ausentes no Kaggle. | Dois itens suplementares, com sete especificações conferidas. São manuais do fabricante publicados em acervos externos; nenhum arquivo ou foto desses sites é redistribuído. |
| Páginas dos fabricantes | Valores específicos usados para resolver conflitos ou preencher lacunas, como socket, TDP, VRAM, tipo e velocidade de memória. | Vinte e nove valores conferidos, incluindo as placas ECS, a GA-Z77X-UD5H, a ASRock A320M-DVS R4.0, o Ryzen 5 5600X e a MSI GTX 1050 Ti 4GT OC. As evidências ficam na curadoria interna; as linhas importadas podem ser consultadas em `GET /items/{id}/sources`. |
| Wikimedia Commons | Fotos de cinco produtos exatos com autoria e licença identificadas. | Referências externas com `image_attribution`. A licença deve ser exibida pelo consumidor. |
| GIGABYTE | Foto oficial da GA-Z77X-UD5H e especificações de memória DDR3. | Imagem vinculada ao modelo exato por URL externa; licença de reutilização não declarada. Memória sem OC até 1600 MHz e com OC até 2800 MHz. |
| [ASRock A320M-DVS R4.0](https://www.asrock.com/mb/AMD/A320M-DVS%20R4.0/A320M-DVS%20R4.0%20Rev%204.02.asp) | Revisões 4.02 e 4.03, tipo de memória, canais e taxas conforme CPU. | Uma revisão lida na placa confirma o modelo; 3200 MHz sem OC depende de CPU Matisse. |
| [Manual.nz](https://www.manual.nz/ecs/a785gm-m3/manual) e [MobileSpecs.net](https://mobilespecs.net/motherboard/ECS/ECS_G41T-MR23_V1-0.html) | Fotos rotuladas como ECS A785GM-M3 e ECS G41T-MR23 V1.0. | URLs externas associadas aos dois itens suplementares; licença de reutilização não identificada e código impresso ilegível nas imagens pequenas. |
| [Dataset público PCPartPicker Parts](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset) | Nomes, marcas, chipsets de GPU e links de imagem. | Revisão fixa do JSONL cruzada por chaves exatas com os itens sem foto: 6.007 URLs novas. Registros ambíguos e placeholders são rejeitados. O dataset é não oficial e os links continuam externos. |
| [BuildCores OpenDB](https://github.com/buildcores/buildcores-open-db) | Cores declaradas e códigos de fabricante para GPUs e placas-mães. | Revisão fixa cruzada por part number e marca: 1.487 cores novas (1.412 GPUs, 75 placas-mães). Correspondências ambíguas são rejeitadas. Os dados derivados em `reported_colors.json` seguem [CC BY-NC-SA 4.0](https://github.com/buildcores/buildcores-open-db/blob/main/LICENSE.txt), com crédito e alterações documentados em [cores](color_enrichment.md). A fonte não fornece licença para fotos de terceiros. |

Os dois arquivos Kaggle completos estão em `data/raw/kaggle/` e são ignorados pelo
Git. O importador preserva todas as colunas originais em `source_records`, associa
linhas somente quando o produto é inequívoco e separa GPUs com chipsets distintos.
Uma URL de imagem entra apenas se parece ser uma foto de produto e não um placeholder.
Isso **não** confirma que ela funciona hoje ou que pode ser republicada.

## Estado da importação validada

Na importação de 14/10/2026, o catálogo validado contém **21.509 itens** e 25.291
linhas de origem importadas: 899 CPUs, 7.549 GPUs, 4.426 placas-mães, 1.707 RAM,
2.313 fontes, 1.571 gabinetes, 872 coolers e 2.172 unidades de armazenamento.
Há **12.673 URLs de imagem** diretamente nos CSVs. Das categorias novas, 2.066 fontes,
1.489 gabinetes, 857 coolers e 1.921 unidades de armazenamento têm URL aproveitável.
Uma linha de fonte com gabinete integrado foi rejeitada porque o mesmo código já
identifica o gabinete; as demais 25.291 linhas passaram. As 11.323 linhas de
`dataset/memory.json` permanecem fora da identificação exata porque seus nomes
não distinguem os kits. Os JSONs de fontes, gabinetes, coolers e discos também não
têm part number nem foto para confirmar um SKU.

### Base anterior (11/10/2026)

| Categoria | Produtos distintos |
| --- | ---: |
| Processadores | 899 |
| Placas de vídeo | 7.549 |
| Placas-mães | 4.426 |
| **Total** | **12.874** |

Foram importadas 16.654 linhas relevantes dos dois arquivos Kaggle, sem rejeições
na execução auditada, mais dois itens suplementares. O importador Kaggle preservou
4.655 URLs externas de imagem. Depois do cruzamento com o export público,
**10.667 itens têm `image_url` e 2.207 permanecem sem foto**. Cinco fotos têm
autoria e licença revisadas; 4.655 URLs anteriores e 6.007 novas associações
externas não tiveram os direitos de cada foto conferidos. A foto oficial da
Gigabyte completa a contagem. A auditoria e o método estão descritos em
[coleta de imagens](image_enrichment.md).

Os arquivos Kaggle não fornecem um ano de lançamento explícito para essas três
categorias. Há produtos antigos, mas a cobertura por década **não foi medida**.
Muitos identificadores entre parênteses precisam de conferência adicional para
serem considerados part numbers oficiais. `GET /items/{id}/sources` expõe as linhas
originais; `specs` mostra valores normalizados e indica conflitos.

## Outras fontes avaliadas, ainda não importadas

| Fonte | Possível benefício | Decisão atual |
| --- | --- | --- |
| [Kaggle: GPU Specs Database 1995–2026](https://www.kaggle.com/datasets/riyagarg0314/gpu-specs-database-nvidia-and-amd-1995-2026) | 1.943 modelos de chip, datas e especificações históricas. | Útil para pesquisa, mas chip genérico não identifica necessariamente a placa de uma fabricante parceira. Não alimentar correspondência exata de SKU com ele. |
| [Open Icecat](https://icecat.com/content-subscription/) | Códigos de produto, GTIN, especificações, datas e referências de imagem. | Exigiria conta, auditoria de cobertura por categoria e cumprimento da [licença](https://iceclog.com/open-content-license/) e da [política de uso](https://iceclog.com/open-icecat-fair-use-policy/). Nenhum dado foi importado. |
| [Wikidata](https://www.wikidata.org/wiki/Wikidata:Data_access) | Dados estruturados CC0 e identificadores. | Pode ajudar a conferir lacunas; cobertura de SKUs e licenças de mídia devem ser avaliadas separadamente. |
| TechPowerUp | Referência histórica de GPU/CPU. | O [robots.txt](https://www.techpowerup.com/robots.txt) restringe mineração e coleta automatizada sem permissão escrita. Sem coleta. |

## Critérios para uma futura ampliação

Antes de acrescentar uma fonte, medir quantidade de produtos por categoria, marca e
década; proporção com código identificável, especificações e imagem; duplicidades e
conflitos; e direitos de uso de dados e fotos. Guarde o registro bruto e sua origem,
rejeite linhas inválidas com motivo e publique uma nova versão do catálogo somente
depois dos controles de qualidade. Correspondências aproximadas continuam como
`suggestions`, nunca como identificação exata.
