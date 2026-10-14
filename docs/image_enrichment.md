# Coleta e associação de imagens

O serviço usa URLs externas como imagens de referência. A coleta é separada do OCR:
uma foto enviada a `/scan` identifica o produto; o catálogo devolve `image_url` da
peça correspondente. O microserviço não tenta reconhecer o modelo pela aparência
da imagem de referência.

## Fonte e execução

O importador usa o [export público JSONL do dataset PCPartPicker Parts](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset).
O arquivo contém nome, marca, categoria, URL do produto, URL da imagem e
especificações. A revisão da fonte e o SHA-256 estão fixados em
`src/scan_hardware/image_enrichment.py`, para que o mesmo input produza o mesmo
manifesto. O [robots.txt do Hugging Face](https://huggingface.co/robots.txt)
permite o download; o [cartão do dataset](https://huggingface.co/datasets/Doshiba/pcpartpicker-parts-dataset/blob/main/README.md)
avisa que é uma coleta não oficial e que URLs podem mudar. Nenhuma página do
PCPartPicker é raspada pelo nosso importador.

Depois de importar o catálogo Kaggle, execute:

```bash
poetry run python -m scan_hardware.image_enrichment --publish-package
poetry run python -m scan_hardware.catalog_audit
```

O primeiro comando baixa um arquivo JSONL de aproximadamente 26 MB para
`data/raw/huggingface/` e o reutiliza em execuções seguintes. Cada execução gera
`data/processed/images/<run-id>/manifest.json` e `report.json`. A opção
`--publish-package` atualiza a cópia empacotada
`src/scan_hardware/curation/external_images.json`; uma cópia da versão anterior
fica no diretório versionado da execução. Reinicie o servidor após atualizar esse
arquivo, pois as associações são carregadas e mantidas em memória.

## Regra para escolher uma foto

O cruzamento usa primeiro o **identificador do anúncio** presente nas duas fontes,
além da categoria e da marca. Isso inclui RAM, fontes, gabinetes, coolers e
armazenamento, mesmo quando os nomes descritivos são diferentes. Na falta desse
identificador, CPU, GPU e placa-mãe usam o **nome original** da linha importada e a
**marca**; para GPU, também exigem igualdade do **chipset**. Só é publicado o
produto com uma única URL de imagem possível. URLs `no-image`, placeholders,
registros inválidos e casos com URLs diferentes para a mesma chave são rejeitados.
O manifesto guarda ID, categoria e modelo do nosso catálogo; se alguém substituir
o item mantendo o ID, a URL externa deixa de ser aplicada.

A prioridade da API é: imagem revisada manualmente, imagem cadastrada no catálogo,
imagem do export exato. Uma imagem local enviada por `PUT /items/{id}/image`
continua prevalecendo no campo `image_url` de `/scan` e `/lookup`.

## Auditoria de 14/10/2026

O novo cruzamento encontrou **140 URLs adicionais** sem retirar ou trocar nenhuma
das 6.007 associações existentes. A cobertura atual inclui todas as oito categorias:

| Categoria | Com imagem | Sem imagem |
| --- | ---: | ---: |
| CPU | 641 | 258 |
| GPU | 6.273 | 1.276 |
| Placa-mãe | 3.814 | 612 |
| RAM | 1.689 | 18 |
| Fonte | 2.085 | 228 |
| Gabinete | 1.494 | 77 |
| Cooler | 864 | 8 |
| Armazenamento | 1.966 | 206 |
| **Total** | **18.826 (87,5%)** | **2.683 (12,5%)** |

Uma URL de cada categoria nova respondeu HTTP 200 com `image/jpeg`. Isso verifica
somente a disponibilidade da amostra: não garante que todas as URLs ainda funcionem
nem que cada foto tenha boa resolução, ângulo ou enquadramento. Os 2.683 itens sem
foto permanecem vazios até surgir fonte identificável para o modelo exato.
Na inspeção visual de três amostras, a GPU, a placa-mãe e a fonte mostraram as
peças esperadas; as duas primeiras vieram em miniaturas de 256 × 256 pixels.

## Resultado da coleta de 12/10/2026

| Categoria | Itens | URLs anteriores | Novas URLs exatas | Com imagem | Sem imagem |
| --- | ---: | ---: | ---: | ---: | ---: |
| CPU | 899 | 291 | 349 | 640 (71,2%) | 259 |
| GPU | 7.549 | 2.243 | 3.986 | 6.229 (82,5%) | 1.320 |
| Placa-mãe | 4.426 | 2.124 | 1.672 | 3.796 (85,8%) | 630 |
| **Total** | **12.874** | **4.658** | **6.007** | **10.665 (82,8%)** | **2.209** |

Esta tabela registra o resultado do cruzamento automático daquele lote. Após a
curadoria manual das imagens ECS A785GM-M3 e G41T-MR23 V1.0, a auditoria atual
conta **10.667 itens com imagem e 2.207 sem imagem**. As fontes e as limitações
dessas duas URLs estão em [validação de campo](field_validation.md).

O importador rejeitou 2.411 placeholders; 368 itens não receberam uma URL porque
mais de uma imagem atendia à mesma chave. Os demais sem foto não tiveram
correspondência exata. O relatório completo local está em
`data/processed/images/20261012T175402123381Z/report.json` na máquina de teste.

Nove URLs selecionadas entre as três categorias responderam HTTP 200 e foram
abertas como JPEG válido. A inspeção visual dessa amostra mostrou placas e GPU
correspondentes ao tipo de produto; uma das imagens de CPU mostra a embalagem
Pentium, e não a face do chip. Isso não prova disponibilidade nem qualidade de
todas as 10.665 URLs. O aplicativo deve mostrar a mensagem de imagem ausente
quando o host externo falhar; o demo já faz isso.

As imagens não são baixadas em massa nem redistribuídas neste repositório. A
licença declarada pelo autor do dataset não comprova os direitos de cada foto
apontada por URL, pois os arquivos continuam hospedados por terceiros. Para uso
fora deste projeto de faculdade, verifique as condições de cada host.
