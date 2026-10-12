# Validação de campo do scanner

Resultados locais em 08, 11 e 12/10/2026. As fotos, manifestos e respostas completas
ficam sob `data/validation/`, fora do Git. Os testes enviaram bytes reais de JPEG
ou PNG para `POST /scan`; não simularam a saída do OCR. Recortes da mesma imagem
são testes de enquadramento, não peças adicionais.

## Foto enviada pelo usuário: Gigabyte GA-Z77X-UD5H

Na foto completa, o OCR inicial leu `GIGABYTE`, mas perdeu o código impresso
`GA-Z77X-UD5H`. Uma segunda leitura com contraste invertido em faixas reconheceu
o código. O catálogo já continha a placa, porém seu identificador tinha o prefixo
`Gigabyte`; o matcher agora também considera o código sem esse prefixo. O envio
da foto completa retornou `matched` exato para `Gigabyte GA-Z77X-UD5H`, ID
`motherboard-2716c8c323f0e5902e139112`. O manifesto local fica em
`data/validation/gigabyte-user-photo-20261012/manifest.json`; o relatório está
em `data/validation/20261012T170433331754Z/report.json` na máquina de teste.

## Foto enviada pelo usuário: três placas ECS

A imagem `placa.jpg` contém três placas empilhadas. A primeira avaliação, antes da
complementação do catálogo, leu os três códigos mas só confirmou `A890GXM-A`.
Depois da inclusão de dois produtos suplementares, os três recortes passaram:

| Código lido | Resultado do recorte | ID encontrado |
| --- | --- | --- |
| `A785GM-M3` | `matched`, exato | `motherboard-ecs-a785gm-m3-v1` |
| `G41T-MR23` | `matched`, exato | `motherboard-ecs-g41t-mr23-v1` |
| `A890GXM-A` | `matched`, exato | `motherboard-b1c7711431a2234604c444f0` |

O envio da montagem inteira também retornou os três itens com `status: matched`.
Isso demonstra o comportamento nessa imagem específica; para uso normal, fotografe
uma peça por vez. O relatório dos recortes está em
`data/validation/20261011T225249516277Z/report.json` na máquina de teste.

Os modelos suplementares foram conferidos nos manuais da ECS para
[A785GM-M3](https://www.scribd.com/document/442253904/A785GM-M3-manual) e
[G41T-MR23](https://www.manualslib.com/manual/453017/Ecs-G41t-Mr23.html).
O primeiro usa socket AM2+/AM2, formato Micro ATX e dois slots DDR2, com máximo
nominal de 16 GB. O manual ressalva que testou 4 GB nas memórias disponíveis à
época. O segundo usa LGA775, formato Micro ATX e até 8 GB em DDR2 **ou** DDR3;
os dois tipos não podem ser usados juntos. Os fatos inseridos no catálogo têm
links para as páginas de evidência. Não foi encontrada uma foto de referência
exata com licença clara para esses modelos; `image_url` permanece `null`.

## Suíte anterior: CPU, GPU e placa-mãe

As oito fotos do manifesto local foram repetidas com o catálogo novo em
11/10/2026. **Oito de oito** mantiveram o resultado esperado. O relatório está
em `data/validation/20261011T225332475553Z/report.json` na máquina de teste.

| Peça e foto | Resultado esperado e observado |
| --- | --- |
| [Intel Core 2 Duo E8400, topo](https://commons.wikimedia.org/wiki/File:Intel_CPU_Core_2_Duo_E8400_Wolfdale_top.jpg) | Código exato e item correto. |
| [E8400, segunda foto](https://commons.wikimedia.org/wiki/File:Intel_Core2Duo_E8400_IMG_8141.jpg) | OCR leu `E8408`; item correto apareceu como sugestão, sem falso exato. |
| [E8400, terceira foto](https://commons.wikimedia.org/wiki/File:Processor_INTEL_CORE_2_DUO.jpg) | OCR leu `E8409`; item correto apareceu como sugestão, sem falso exato. |
| [MSI GTX 1050 Ti 4GT OC, verso](https://commons.wikimedia.org/wiki/File:MSI_GeForce_GTX_1050_Ti_4GT_OC_-_rear_view.jpg) | Código exato e item correto. |
| [Intel Core i5-2500K](https://commons.wikimedia.org/wiki/File:Intel_Core_i5-2500K_20110418.jpg) | Item correto como sugestão. |
| [ASUS Dual GTX 1060 3GB, verso](https://commons.wikimedia.org/wiki/File:ASUS_Dual_GeForce_GTX_1060_3GB_OC_Edition_-_rear_view.jpg) | Item correto como sugestão. |
| [ASRock A320M-DVS](https://commons.wikimedia.org/wiki/File:2023_P%C5%82yta_g%C5%82%C3%B3wna_ASRock_A320M-DVS.jpg) | Revisão ilegível: item correto como sugestão. |
| [MSI GTX 1050 Ti, frente sem código](https://commons.wikimedia.org/wiki/File:MSI_GTX_1050_TI_4GT_LP.jpg) | `not_found`; a identificação não aparece na face fotografada. |

Licenças e autores das fotos externas estão no
[manifesto de exemplo](photo_manifest.example.json). Esses doze ensaios cobrem
poucos produtos e não representam uma taxa geral de acerto do OCR.

## Cobertura e conflitos dos dados

Auditoria do catálogo publicado em 11/10/2026. `coverage` conta itens com valor
de fonte ou fato conferido; um conflito conta como coberto, mas retorna
`value: null` até ser resolvido. O relatório completo está em
`data/audit/20261011T225411477300Z/report.json` na máquina de teste.

| Categoria e total | Campo | Cobertura | Conflitos restantes |
| --- | --- | ---: | ---: |
| CPU (899) | Núcleos | 899 | 48 |
| CPU (899) | Clock base | 899 | 0 |
| CPU (899) | TDP | 899 | 227 |
| CPU (899) | Socket | 319 | 0 |
| CPU (899) | Threads | 318 | 0 |
| CPU (899) | Clock boost | 456 | 0 |
| GPU (7.549) | VRAM | 7.291 | 103 |
| GPU (7.549) | Chipset | 5.248 | 0 |
| GPU (7.549) | Potência da placa | 2.514 | 0 |
| Placa-mãe (4.426) | Socket | 4.426 | 161 |
| Placa-mãe (4.426) | Formato | 4.426 | 1.232 |
| Placa-mãe (4.426) | Memória máxima | 4.229 | 1 |
| Placa-mãe (4.426) | Slots de memória | 4.228 | 1 |

Vinte e cinco valores de itens específicos foram conferidos em documentos identificados:
socket do E8400; TDP do i3-7350K; VRAM da MSI GTX 1050 Ti 4GT OC; formato da
ASRock A320M-DVS R4.0; quatro campos da A785GM-M3; três da G41T-MR23; e três
campos de memória da GA-Z77X-UD5H, mais tipo de slot e canais dessa placa;
tipo e taxa de RAM, caches L2/L3 e TDP do Ryzen 5 5600X; e tipo, velocidade,
barramento e unidades de processamento da MSI GTX 1050 Ti 4GT OC.
As evidências originais dos arquivos Kaggle continuam acessíveis em
`GET /items/{id}/sources`.

## Imagens e limites

A foto enviada da GA-Z77X-UD5H passou a resolver uma imagem externa do
[fabricante](https://www.gigabyte.com/Motherboard/GA-Z77X-UD5H-rev-10), sem
redistribuir o arquivo. A página de [especificações da GIGABYTE](https://www.gigabyte.com/Motherboard/GA-Z77X-UD5H-rev-10/sp)
informa DDR3, 32 GB em quatro slots, até 1600 MHz sem OC e 2800 MHz com OC.
O demo agora mostra a unidade de memória e distingue o limite com overclock.
As fichas do [Ryzen 5 5600X](https://www.amd.com/en/products/processors/desktops/ryzen/5000-series/amd-ryzen-5-5600x.html)
e da [MSI GTX 1050 Ti 4GT OC](https://www.msi.com/Graphics-Card/GeForce-GTX-1050-Ti-4GT-OC/Specification)
fornecem os novos detalhes de CPU e GPU. O fluxo com fotos foi repetido em
12/10/2026: oito casos anteriores passaram, incluindo CPU, GPU e placa-mãe;
a foto enviada da GA-Z77X-UD5H também retornou o item exato. Relatórios locais:
`data/validation/20261012T173651826111Z/report.json` e
`data/validation/20261012T173704630640Z/report.json`.

O importador removeu placeholders conhecidos. Depois da
[coleta por correspondência exata](image_enrichment.md), a auditoria conta cinco
fotos com autoria e licença revisadas, 4.653 URLs anteriores sem direitos
revisados, 6.007 novas URLs externas e 2.209 itens sem imagem. As fotos continuam
hospedadas fora do serviço. Uma amostra de nove URLs novas respondeu HTTP 200
com JPEG válido; a inspeção visual de CPU, GPU e placa-mãe mostrou que uma imagem
de CPU era da embalagem do processador. Isso não comprova a qualidade de todo o
catálogo nem dá licença para republicar os arquivos.

O serviço e a configuração Compose foram testados localmente. A construção e a
execução do contêiner **não puderam ser realizadas nesta máquina**, pois o daemon
Docker não estava ativo; o CI agora inclui a construção da imagem no runner Linux.
Também não foi medida a latência da rede celular nem foi testada uma câmera em
aparelho físico. Fotos sem código visível, reflexos e revisões muito parecidas
continuam exigindo mais ensaios antes de uso em produção.
